"""NAS100 opening-range backtesting configuration.

The $75/$150 values mirror the user's stated baseline. The $1-per-point-per-lot
contract value is an assumption and must be checked against the broker's NAS100
contract specification before interpreting lot size or simulated USD P&L.
"""

INSTRUMENT = "NAS100"
DATA_FILE = "data/NAS100_Dukascopy_1y.csv"
TIMEZONE = "America/New_York"

# Opening range: first 60 one-minute candles of the regular US cash session.
OR_START = "09:30"
OR_END = "10:30"

# New entries are allowed for the next two hours after the opening range.
TRADING_START = "10:30"
TRADING_END = "12:30"

# Baseline risk and reward.
RISK_PER_TRADE_USD = 75.0
TARGET_PROFIT_USD = 150.0
STOP_LOSS_POINTS = 20.0
TAKE_PROFIT_POINTS = 40.0

# IMPORTANT: verify this against the exact broker symbol/contract.
# For $1 per point per lot, $75 risk over a 20-point stop = 3.75 lots.
DOLLARS_PER_POINT_PER_LOT = 1.0

POSITION_SIZE_LOTS = (
    RISK_PER_TRADE_USD
    / (STOP_LOSS_POINTS * DOLLARS_PER_POINT_PER_LOT)
)

# Strategy limits.
MAX_TRADES_PER_DAY = 2

# Execution assumptions. Zero means costs are currently NOT simulated.
SPREAD_POINTS = 0.0
SLIPPAGE_POINTS = 0.0

# When both boundaries are inside one OHLC candle, OHLC data cannot show
# which boundary was touched first. "skip" avoids inventing an intrabar order.
AMBIGUOUS_SL_TP_POLICY = "stop_first"
AMBIGUOUS_OR_TOUCH_POLICY = "skip"

# Confirmed rule: no new entries after 12:30, but existing positions remain
# open until SL or TP, including across subsequent sessions.
FORCE_CLOSE_AT_SESSION_END = False
