# region imports
from AlgorithmImports import *
# endregion

# ── Risk parameters (edit these) ─────────────────────────────────────────────
STOP_LOSS_PCT   = 0.07   # exit if price drops 7% below entry
TAKE_PROFIT_PCT = 0.15   # exit if price rises 15% above entry

class IchimokuSartexStrategy(QCAlgorithm):
    """
    Ichimoku Cloud + Parabolic SAR (Sartex) strategy for RELIANCE (NSE).

    Entry (Long):
        - Price is above the cloud  (above both Senkou A and Senkou B)
        - Tenkan-sen > Kijun-sen    (bullish momentum)
        - PSAR < current price      (SAR below price = uptrend)

    Exit (signal):
        - PSAR > current price      (SAR flips above = trend reversal)
        - OR Tenkan-sen < Kijun-sen (momentum turns bearish)

    Exit (risk):
        - Price falls STOP_LOSS_PCT below entry   (hard stop loss)
        - Price rises TAKE_PROFIT_PCT above entry (take profit)
    """

    def initialize(self):
        self.set_start_date(2020, 5, 17)
        self.set_end_date(2026, 5, 17)
        self.set_cash(100_000)

        # ── Security ──────────────────────────────────────────────────────────
        equity = self.add_equity("RELIANCE", Resolution.DAILY, Market.India)
        equity.set_fee_model(ConstantFeeModel(20))   # flat ₹20 per order (Zerodha)
        self._sym = equity.symbol

        # ── Ichimoku Kinko Hyo ────────────────────────────────────────────────
        self._ichi = self.ichimoku(
            self._sym,
            9,    # Tenkan-sen period
            26,   # Kijun-sen period
            26,   # Senkou A offset (displacement forward)
            52,   # Senkou B period
            26,   # Senkou B offset
            26,   # Chikou offset
            Resolution.DAILY
        )

        # ── Parabolic SAR (Sartex) ────────────────────────────────────────────
        self._psar = self.psar(
            self._sym,
            0.02,   # initial acceleration factor
            0.02,   # acceleration increment per new extreme
            0.2,    # maximum acceleration factor
            Resolution.DAILY
        )

        # Warmup: Ichimoku needs 52 (senkou_b) + 26 (displacement) = 78 bars minimum
        self.set_warm_up(100, Resolution.DAILY)

        self._traded_today = False
        self._entry_price  = None

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return
        if not data.bars.contains_key(self._sym):
            return
        if self._traded_today:
            return
        if not self._ichi.is_ready or not self._psar.is_ready:
            return

        price = data.bars[self._sym].close

        # ── Indicator values ──────────────────────────────────────────────────
        tenkan   = self._ichi.tenkan.current.value
        kijun    = self._ichi.kijun.current.value
        senkou_a = self._ichi.senkou_a.current.value
        senkou_b = self._ichi.senkou_b.current.value
        sar      = self._psar.current.value

        cloud_top    = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        # ── Entry conditions ──────────────────────────────────────────────────
        above_cloud      = price > cloud_top
        bullish_momentum = tenkan > kijun
        sar_below_price  = sar < price

        # ── Exit conditions ───────────────────────────────────────────────────
        sar_above_price  = sar > price
        bearish_momentum = tenkan < kijun

        stop_hit   = (self._entry_price is not None and
                      price <= self._entry_price * (1 - STOP_LOSS_PCT))
        profit_hit = (self._entry_price is not None and
                      price >= self._entry_price * (1 + TAKE_PROFIT_PCT))

        invested = self.portfolio[self._sym].invested
        has_open_order = bool(self.transactions.get_open_orders(self._sym))

        if not invested and not has_open_order:
            if above_cloud and bullish_momentum and sar_below_price:
                self.set_holdings(self._sym, 1.0)
                self._entry_price = price
                self.log(
                    f"LONG  | price={price:.2f}  SAR={sar:.2f}  "
                    f"tenkan={tenkan:.2f}  kijun={kijun:.2f}  "
                    f"cloud=[{cloud_bottom:.2f}, {cloud_top:.2f}]  "
                    f"stop={price*(1-STOP_LOSS_PCT):.2f}  target={price*(1+TAKE_PROFIT_PCT):.2f}"
                )
                self._traded_today = True
        elif invested and not has_open_order:
            if stop_hit or profit_hit or sar_above_price or bearish_momentum:
                self.liquidate(self._sym)
                if stop_hit:
                    reason = f"STOP LOSS ({STOP_LOSS_PCT*100:.0f}%)"
                elif profit_hit:
                    reason = f"TAKE PROFIT ({TAKE_PROFIT_PCT*100:.0f}%)"
                elif sar_above_price:
                    reason = "SAR flip"
                else:
                    reason = "Tenkan/Kijun cross"
                self.log(
                    f"EXIT  | {reason}  price={price:.2f}  entry={self._entry_price:.2f}  "
                    f"SAR={sar:.2f}  tenkan={tenkan:.2f}  kijun={kijun:.2f}"
                )
                self._entry_price = None
                self._traded_today = True

    def on_end_of_day(self, symbol):
        self._traded_today = False

    def on_end_of_algorithm(self):
        self.log(f"Final portfolio value: {self.portfolio.total_portfolio_value:,.2f}")
