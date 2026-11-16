# NAS100 opening-range backtest

This folder contains a historical 1-minute NAS100 opening-range backtest and
experimental variants. The baseline settings are in `config.py`.

## Baseline strategy settings

- Opening range: 09:30–10:30 America/New_York.
- Entry window: 10:30–12:30 America/New_York.
- Entry trigger: wick touches an opening-range boundary.
- Initial OR high touch: SELL; initial OR low touch: BUY.
- Stop: 20 points; target: 40 points.
- Risk budget: $75 per trade; target budget: $150 per trade.
- Maximum: two trades per trading day.
- If the first trade hits SL, the second setup waits for a touch of the first
  entry price and takes the opposite direction.
- If the first trade hits TP, trading stops for that day; no second trade is
  opened.
- A maximum of two trades are allowed per trading day.
- No new entries are opened after 12:30. Existing positions remain active
  until SL or TP, including after 12:30 and across subsequent sessions.
- The current simulator does not open a new trade on the same candle that
  closes the previous trade.

These are intended backtest rules, not evidence of a profitable strategy.

## Historical data is not included

The CSV files are intentionally excluded from Git. Place your own authorized
1-minute historical data file at:

```text
nas100-backtest/data/NAS100_Dukascopy_1y.csv
```

The loader expects these columns:

```text
datetime,open,high,low,close,volume
```

The data loader interprets timestamps as UTC and converts them to the
`America/New_York` timezone. Confirm the source timestamps really are UTC
before using the results. Do not commit licensed datasets, large raw files,
broker credentials or account information.

## Install and run

From the repository root, using Python 3.8+:

```powershell
python -m pip install pandas
python nas100-backtest/data_loader.py
python nas100-backtest/opening_range.py
python nas100-backtest/trade_simulator.py
```

Run the repository tests:

```powershell
python -m unittest discover -s tests -v
```

## Validate data and trade results

The new `validation.py` module provides reusable checks for timezone-aware
OHLCV data, candle bounds, baseline settings, trade arithmetic and the
two-trades-per-day limit. It does not modify the simulator's entry/exit logic.

## Important limitations to resolve before relying on results

1. **Contract value:** `DOLLARS_PER_POINT_PER_LOT = 1.0` is an assumption.
   Verify the exact NAS100 product's contract specification with the broker.
   At that assumed value, 20 points × 3.75 lots × $1 = $75 risk, and 40 points
   × 3.75 lots × $1 = $150 target. Other contract values produce a different
   lot size.
2. **Trading costs:** spread and slippage settings are currently zero and are
   not yet deducted by the baseline simulator. Backtest P&L is therefore
   gross of those costs.
3. **Both OR boundaries in one minute:** OHLC data reveals that both levels
   were inside the candle, but not which was touched first. The current
   simulator skips that ambiguous candle. Tick or lower-timeframe data is
   needed to enforce a true first-touch rule without guessing.
4. **Session end:** the confirmed rule is no new entries after 12:30, while
   existing positions remain active until SL or TP, even across sessions.
5. **Intrabar fills:** 1-minute OHLC candles cannot reconstruct the exact order
   of every event inside a candle. The simulator uses conservative assumptions
   in selected ambiguous cases; results should be checked against tick data
   before any live use.

Use this project for research and paper testing only until the execution model,
data provenance and broker contract value have been independently verified.
