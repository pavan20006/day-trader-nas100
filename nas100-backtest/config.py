"""NAS100 opening-range backtesting configuration."""

INSTRUMENT = "NAS100"
DATA_FILE = "data/NAS100_Dukascopy_1y.csv"
TIMEZONE = "America/New_York"

# Opening range
OR_START = "09:30"
OR_END = "10:30"

# Trading session
TRADING_START = "10:30"
TRADING_END = "12:30"

# Risk and reward
RISK_PER_TRADE_USD = 25.0
TARGET_PROFIT_USD = 50.0
STOP_LOSS_POINTS = 20.0
TAKE_PROFIT_POINTS = 40.0
DOLLARS_PER_POINT_PER_LOT = 1.0

# Automatically calculated position size
POSITION_SIZE_LOTS = (
    RISK_PER_TRADE_USD
    / (STOP_LOSS_POINTS * DOLLARS_PER_POINT_PER_LOT)
)

# Strategy limits
MAX_TRADES_PER_DAY = 2

# Execution assumptions
SPREAD_POINTS = 0.0
SLIPPAGE_POINTS = 0.0

# Ambiguous candle policies
AMBIGUOUS_SL_TP_POLICY = "stop_first"
AMBIGUOUS_OR_TOUCH_POLICY = "skip"

# Session handling
FORCE_CLOSE_AT_SESSION_END = False
