# region imports
from AlgorithmImports import *
# endregion

# ── Risk parameters ───────────────────────────────────────────────────────────
STOP_LOSS_PCT   = 0.07
TAKE_PROFIT_PCT = 0.15

RSI_PERIOD   = 14
RSI_OVERSOLD  = 30
RSI_OVERBOUGHT = 70

class RsiHdfcBankStrategy(QCAlgorithm):
    """
    RSI strategy for HDFCBANK (NSE) on hourly bars.

    Entry (Long):
        - RSI crosses up through RSI_OVERSOLD (30)

    Exit (signal):
        - RSI crosses up through RSI_OVERBOUGHT (70)

    Exit (risk):
        - Price falls STOP_LOSS_PCT below entry   (hard stop loss)
        - Price rises TAKE_PROFIT_PCT above entry (take profit)
    """

    def initialize(self):
        self.set_start_date(2024, 5, 22)
        self.set_end_date(2026, 5, 18)
        self.set_cash(100_000)

        equity = self.add_equity("HDFCBANK", Resolution.HOUR, Market.India)
        equity.set_fee_model(ConstantFeeModel(20))
        self._sym = equity.symbol

        # Resolution inferred from subscription — no need to pass it
        self._rsi = self.rsi(self._sym, RSI_PERIOD)

        self.set_warm_up(RSI_PERIOD + 1, Resolution.HOUR)

        self._entry_price = None
        self._prev_rsi    = None

    def on_data(self, data: Slice):
        if self.is_warming_up:
            return
        if not self._rsi.is_ready:
            return
        if not data.bars.contains_key(self._sym):
            return

        price   = data.bars[self._sym].close
        rsi_val = self._rsi.current.value

        stop_hit   = (self._entry_price is not None and
                      price <= self._entry_price * (1 - STOP_LOSS_PCT))
        profit_hit = (self._entry_price is not None and
                      price >= self._entry_price * (1 + TAKE_PROFIT_PCT))
        overbought = (self._prev_rsi is not None and
                      self._prev_rsi < RSI_OVERBOUGHT and rsi_val >= RSI_OVERBOUGHT)

        oversold_cross = (self._prev_rsi is not None and
                          self._prev_rsi < RSI_OVERSOLD and rsi_val >= RSI_OVERSOLD)

        invested       = self.portfolio[self._sym].invested
        has_open_order = bool(self.transactions.get_open_orders(self._sym))

        if not invested and not has_open_order:
            if oversold_cross:
                self.set_holdings(self._sym, 1.0)
                self._entry_price = price
                self.log(
                    f"LONG  | price={price:.2f}  RSI={rsi_val:.2f}  "
                    f"stop={price*(1-STOP_LOSS_PCT):.2f}  target={price*(1+TAKE_PROFIT_PCT):.2f}"
                )
        elif invested and not has_open_order:
            if stop_hit or profit_hit or overbought:
                self.liquidate(self._sym)
                if stop_hit:
                    reason = f"STOP LOSS ({STOP_LOSS_PCT*100:.0f}%)"
                elif profit_hit:
                    reason = f"TAKE PROFIT ({TAKE_PROFIT_PCT*100:.0f}%)"
                else:
                    reason = f"RSI OVERBOUGHT ({rsi_val:.2f})"
                self.log(
                    f"EXIT  | {reason}  price={price:.2f}  entry={self._entry_price:.2f}  "
                    f"RSI={rsi_val:.2f}"
                )
                self._entry_price = None

        self._prev_rsi = rsi_val

    def on_end_of_algorithm(self):
        self.log(f"Final portfolio value: {self.portfolio.total_portfolio_value:,.2f}")
