# region imports
from AlgorithmImports import *
# endregion

# ── Parameters ────────────────────────────────────────────────────────────────
RSI_PERIOD    = 14
RSI_BUY       = 55       # RSI must be above for long entry
RSI_SELL      = 45       # RSI must be below for short entry

PSAR_AF_START = 0.02
PSAR_AF_STEP  = 0.02
PSAR_AF_MAX   = 0.2

EMA_PERIOD    = 200

ADX_PERIOD    = 14
ADX_THRESHOLD = 25       # only trade in trending markets

SWING_LOOKBACK = 10      # bars to look back for swing high/low stop
RR_RATIO       = 2.0     # take profit = risk × RR_RATIO

class RsiSarStrategy(QCAlgorithm):
    """
    RSI + Parabolic SAR strategy for TATASTEEL (NSE) on hourly bars.

    BUY (Long):
        - SAR flips below candles (bullish flip)
        - RSI > 55
        - Price > 200 EMA
        - ADX > 25
    Stop : below previous swing low (last SWING_LOOKBACK bars)
    TP   : stop distance × RR_RATIO  OR  SAR flips above (whichever first)

    SELL (Short):
        - SAR flips above candles (bearish flip)
        - RSI < 45
        - Price < 200 EMA
        - ADX > 25
    Stop : above previous swing high
    TP   : stop distance × RR_RATIO  OR  SAR flips below (whichever first)
    """

    def initialize(self):
        self.set_start_date(2024, 5, 28)
        self.set_end_date(2026, 5, 21)
        # self.set_cash(2_000)

        equity = self.add_equity("RELIANCE", Resolution.HOUR, Market.India)
        equity.set_fee_model(ConstantFeeModel(0))  # Zerodha: ~₹0.60 on ₹2000 = negligible
        self._sym = equity.symbol

        # ── Indicators ────────────────────────────────────────────────────────
        self._rsi  = self.rsi(self._sym, RSI_PERIOD)
        self._psar = self.psar(self._sym, PSAR_AF_START, PSAR_AF_STEP, PSAR_AF_MAX)
        self._ema  = self.ema(self._sym, EMA_PERIOD)
        self._adx  = self.adx(self._sym, ADX_PERIOD)

        # Rolling window to find swing high/low for stop placement
        self._highs = RollingWindow[float](SWING_LOOKBACK)
        self._lows  = RollingWindow[float](SWING_LOOKBACK)

        # Warm up for slowest indicator (EMA 200)
        self.set_warm_up(EMA_PERIOD + SWING_LOOKBACK, Resolution.HOUR)

        self._prev_sar    = None
        self._prev_price  = None
        self._entry_price = None
        self._stop_price  = None
        self._tp_price    = None
        self._direction   = None   # "long" or "short"

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return
        if not all([self._rsi.is_ready, self._psar.is_ready,
                    self._ema.is_ready, self._adx.is_ready]):
            return
        if not data.bars.contains_key(self._sym):
            return

        bar   = data.bars[self._sym]
        price = bar.close

        rsi_val = self._rsi.current.value
        sar_val = self._psar.current.value
        ema_val = self._ema.current.value
        adx_val = self._adx.current.value

        # Update rolling windows with current bar
        self._highs.add(bar.high)
        self._lows.add(bar.low)

        # ── SAR flip detection ────────────────────────────────────────────────
        sar_was_above    = (self._prev_sar is not None and self._prev_sar > self._prev_price)
        sar_was_below    = (self._prev_sar is not None and self._prev_sar < self._prev_price)
        sar_flipped_below = sar_was_above and sar_val < price   # bullish flip
        sar_flipped_above = sar_was_below and sar_val > price   # bearish flip

        invested       = self.portfolio[self._sym].invested
        has_open_order = bool(self.transactions.get_open_orders(self._sym))

        if not invested and not has_open_order:

            # ── Long entry ────────────────────────────────────────────────────
            if (sar_flipped_below and
                    rsi_val > RSI_BUY and
                    price > ema_val and
                    adx_val > ADX_THRESHOLD and
                    self._lows.is_ready):

                swing_low = min(list(self._lows))
                risk      = price - swing_low
                if risk > 0:
                    qty = max(1, int(2_000 / price))
                    self.market_order(self._sym, qty)
                    self._entry_price = price
                    self._stop_price  = swing_low
                    self._tp_price    = price + risk * RR_RATIO
                    self._direction   = "long"
                    self.log(
                        f"LONG  | price={price:.2f}  SAR={sar_val:.2f}  RSI={rsi_val:.2f}  "
                        f"EMA={ema_val:.2f}  ADX={adx_val:.2f}  "
                        f"stop={self._stop_price:.2f}  tp={self._tp_price:.2f}"
                    )

            # ── Short entry ───────────────────────────────────────────────────
            elif (sar_flipped_above and
                    rsi_val < RSI_SELL and
                    price < ema_val and
                    adx_val > ADX_THRESHOLD and
                    self._highs.is_ready):

                swing_high = max(list(self._highs))
                risk       = swing_high - price
                if risk > 0:
                    qty = max(1, int(2_000 / price))
                    self.market_order(self._sym, -qty)
                    self._entry_price = price
                    self._stop_price  = swing_high
                    self._tp_price    = price - risk * RR_RATIO
                    self._direction   = "short"
                    self.log(
                        f"SHORT | price={price:.2f}  SAR={sar_val:.2f}  RSI={rsi_val:.2f}  "
                        f"EMA={ema_val:.2f}  ADX={adx_val:.2f}  "
                        f"stop={self._stop_price:.2f}  tp={self._tp_price:.2f}"
                    )

        elif invested and not has_open_order:
            reason = None

            if self._direction == "long":
                if price <= self._stop_price:
                    reason = f"STOP LOSS ({self._stop_price:.2f})"
                elif price >= self._tp_price:
                    reason = f"TAKE PROFIT 1:2 ({self._tp_price:.2f})"
                elif sar_flipped_above:
                    reason = "SAR flip bearish"

            elif self._direction == "short":
                if price >= self._stop_price:
                    reason = f"STOP LOSS ({self._stop_price:.2f})"
                elif price <= self._tp_price:
                    reason = f"TAKE PROFIT 1:2 ({self._tp_price:.2f})"
                elif sar_flipped_below:
                    reason = "SAR flip bullish"

            if reason:
                self.liquidate(self._sym)
                self.log(
                    f"EXIT  | {reason}  price={price:.2f}  entry={self._entry_price:.2f}  "
                    f"RSI={rsi_val:.2f}  SAR={sar_val:.2f}"
                )
                self._entry_price = None
                self._stop_price  = None
                self._tp_price    = None
                self._direction   = None

        self._prev_sar   = sar_val
        self._prev_price = price

    def on_end_of_algorithm(self):
        self.log(f"Final portfolio value: {self.portfolio.total_portfolio_value:,.2f}")
