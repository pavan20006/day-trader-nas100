from pathlib import Path
import sys

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import load_data
import config


# ============================================================
# NAS100: 15M EMA TREND + 5M PULLBACK + 1M EXECUTION
# ============================================================

RISK_USD = 25.0
REWARD_RISK = 2.0
STOP_BUFFER_POINTS = 1.0
MAX_TRADES_PER_DAY = 3

SESSION_START = "09:30"
SESSION_END = "12:30"

TREND_EMA_FAST = 50
TREND_EMA_SLOW = 200


def make_candles(data, timeframe):
    df = data.set_index("datetime").sort_index()

    candles = df.resample(
        timeframe, closed="left", label="right"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })

    return candles.dropna(subset=["open", "high", "low", "close"])


def build_signals(data):
    m15 = make_candles(data, "15min")
    m5 = make_candles(data, "5min")

    # Trend indicators use completed 15-minute candles.
    m15["ema50"] = m15["close"].ewm(
        span=TREND_EMA_FAST,
        adjust=False,
        min_periods=TREND_EMA_FAST,
    ).mean()

    m15["ema200"] = m15["close"].ewm(
        span=TREND_EMA_SLOW,
        adjust=False,
        min_periods=TREND_EMA_SLOW,
    ).mean()

    trend = m15[["ema50", "ema200"]].reset_index()
    trend.columns = ["trend_close_time", "ema50", "ema200"]

    setup = m5.reset_index()
    setup.columns = [
        "signal_time", "open", "high", "low", "close", "volume"
    ]

    # Attach only the latest completed 15-minute trend candle.
    setup = pd.merge_asof(
        setup.sort_values("signal_time"),
        trend.sort_values("trend_close_time"),
        left_on="signal_time",
        right_on="trend_close_time",
        direction="backward",
        allow_exact_matches=True,
    )

    setup["date"] = setup["signal_time"].dt.date
    setup["clock"] = setup["signal_time"].dt.strftime("%H:%M")

    signals = []

    for _, row in setup.iterrows():
        if pd.isna(row["ema50"]) or pd.isna(row["ema200"]):
            continue

        if not (SESSION_START <= row["clock"] < SESSION_END):
            continue

        ema50 = float(row["ema50"])
        ema200 = float(row["ema200"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        # Bullish trend: 15M EMA50 above EMA200.
        if ema50 > ema200:
            # Pullback touches EMA50 and closes back above it.
            if low <= ema50 and close > ema50:
                signals.append({
                    "date": row["date"],
                    "signal_time": row["signal_time"],
                    "direction": "BUY",
                    "pullback_extreme": low,
                    "setup": "BULLISH_EMA_PULLBACK",
                })

        # Bearish trend: 15M EMA50 below EMA200.
        elif ema50 < ema200:
            # Pullback touches EMA50 and closes back below it.
            if high >= ema50 and close < ema50:
                signals.append({
                    "date": row["date"],
                    "signal_time": row["signal_time"],
                    "direction": "SELL",
                    "pullback_extreme": high,
                    "setup": "BEARISH_EMA_PULLBACK",
                })

    return signals


def simulate():
    data = load_data().sort_values("datetime").reset_index(drop=True)

    signals = build_signals(data)

    # Map each signal to the first available M1 candle at or after
    # its completed 5-minute candle close.
    minute_times = data["datetime"].tolist()
    signals_by_index = {}

    for signal in signals:
        import bisect
        index = bisect.bisect_left(minute_times, signal["signal_time"])

        if index >= len(data):
            continue

        signals_by_index.setdefault(index, []).append(signal)

    trades = []
    position = None
    daily_counts = {}
    equity = 0.0
    equity_peak = 0.0
    max_drawdown = 0.0

    def close_position(candle, exit_price, outcome):
        nonlocal position, equity, equity_peak, max_drawdown

        if position["direction"] == "BUY":
            points = exit_price - position["entry"]
        else:
            points = position["entry"] - exit_price

        pnl = (
            points
            * position["lots"]
            * config.DOLLARS_PER_POINT_PER_LOT
        )

        equity += pnl
        equity_peak = max(equity_peak, equity)
        max_drawdown = max(max_drawdown, equity_peak - equity)

        trades.append({
            "date": position["date"],
            "trade_number": position["trade_number"],
            "setup": position["setup"],
            "direction": position["direction"],
            "entry_time": position["entry_time"],
            "exit_time": candle["datetime"],
            "entry": position["entry"],
            "exit": float(exit_price),
            "stop_loss": position["stop"],
            "take_profit": position["target"],
            "risk_points": position["risk_points"],
            "lots": position["lots"],
            "points": points,
            "pnl_usd": pnl,
            "outcome": outcome,
        })

        position = None

    for index, candle in data.iterrows():
        high = float(candle["high"])
        low = float(candle["low"])
        open_price = float(candle["open"])

        # Manage an existing position before considering new entries.
        if position is not None:
            if position["direction"] == "BUY":
                if open_price <= position["stop"]:
                    close_position(candle, open_price, "SL")
                elif open_price >= position["target"]:
                    close_position(candle, open_price, "TP")
                elif low <= position["stop"]:
                    close_position(candle, position["stop"], "SL")
                elif high >= position["target"]:
                    close_position(candle, position["target"], "TP")

            else:
                if open_price >= position["stop"]:
                    close_position(candle, open_price, "SL")
                elif open_price <= position["target"]:
                    close_position(candle, open_price, "TP")
                elif high >= position["stop"]:
                    close_position(candle, position["stop"], "SL")
                elif low <= position["target"]:
                    close_position(candle, position["target"], "TP")

            # Never open another trade on the candle that closes a trade.
            if position is not None:
                continue
            else:
                continue

        # No new entries outside the New York morning session.
        clock = candle["time"]
        if not (SESSION_START <= clock < SESSION_END):
            continue

        for signal in signals_by_index.get(index, []):
            trading_date = signal["date"]
            count = daily_counts.get(trading_date, 0)

            if count >= MAX_TRADES_PER_DAY:
                continue

            direction = signal["direction"]

            # Entry at the next available M1 candle open.
            entry = open_price

            if direction == "BUY":
                stop = signal["pullback_extreme"] - STOP_BUFFER_POINTS
                risk_points = entry - stop
                target = entry + REWARD_RISK * risk_points
            else:
                stop = signal["pullback_extreme"] + STOP_BUFFER_POINTS
                risk_points = stop - entry
                target = entry - REWARD_RISK * risk_points

            if risk_points <= 0:
                continue

            lots = RISK_USD / (
                risk_points * config.DOLLARS_PER_POINT_PER_LOT
            )

            daily_counts[trading_date] = count + 1

            position = {
                "date": trading_date,
                "trade_number": count + 1,
                "setup": signal["setup"],
                "direction": direction,
                "entry_time": candle["datetime"],
                "entry": entry,
                "stop": stop,
                "target": target,
                "risk_points": risk_points,
                "lots": lots,
            }

            # Check SL/TP on the entry candle too.
            # If both are touched, SL is counted first.
            if direction == "BUY":
                if low <= stop:
                    close_position(candle, stop, "SL")
                elif high >= target:
                    close_position(candle, target, "TP")
            else:
                if high >= stop:
                    close_position(candle, stop, "SL")
                elif low <= target:
                    close_position(candle, target, "TP")

            break

    return {
        "trades": trades,
        "open_position": position,
        "signals": signals,
        "max_drawdown": max_drawdown,
    }


if __name__ == "__main__":
    results = simulate()
    trades = results["trades"]

    print("NAS100 EMA PULLBACK BACKTEST")
    print("Signals:", len(results["signals"]))
    print("Completed trades:", len(trades))
    print("Open position:", results["open_position"])

    if trades:
        wins = sum(t["outcome"] == "TP" for t in trades)
        losses = sum(t["outcome"] == "SL" for t in trades)
        pnl = sum(t["pnl_usd"] for t in trades)

        gross_profit = sum(
            t["pnl_usd"] for t in trades if t["pnl_usd"] > 0
        )
        gross_loss = abs(sum(
            t["pnl_usd"] for t in trades if t["pnl_usd"] < 0
        ))

        profit_factor = (
            gross_profit / gross_loss if gross_loss else float("inf")
        )

        print("Wins:", wins)
        print("Losses:", losses)
        print("Win rate:", round(wins / len(trades) * 100, 2), "%")
        print("Net P/L: $", round(pnl, 2))
        print("Profit factor:", round(profit_factor, 3))
        print("Maximum drawdown: $", round(results["max_drawdown"], 2))

        print("\nLast 10 trades:")
        for trade in trades[-10:]:
            print(trade)
    else:
        print("No completed trades found.")
