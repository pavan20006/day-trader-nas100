from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import load_data
import config


# ============================================================
# LIQUIDITY SWEEP + 4H EMA + 15M MSS STRATEGY
# ============================================================

RISK_USD = 25.0
REWARD_RISK = 2.0
DOLLARS_PER_POINT_PER_LOT = 1.0
STOP_BUFFER_POINTS = 1.0

ASIAN_START = "00:00"
ASIAN_END = "08:00"
ENTRY_START = "09:30"
ENTRY_END = "11:30"
DAY_END = "16:00"

EMA_PERIOD = 50
ATR_PERIOD = 14
ATR_NEUTRAL_MULTIPLIER = 0.10

MAX_TRADES_PER_DAY = 2
MAX_DAILY_LOSSES = 2


def build_timeframes(data):
    df = data.copy().set_index("datetime").sort_index()

    # 15-minute candles, labelled by their closing timestamp.
    m15 = df.resample(
        "15min", closed="left", label="right"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])

    # Four-hour candles, labelled by their closing timestamp.
    h4 = df.resample(
        "4h", closed="left", label="right",
        origin="start_day"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])

    h4["ema50"] = h4["close"].ewm(
        span=EMA_PERIOD, adjust=False, min_periods=EMA_PERIOD
    ).mean()

    previous_close = h4["close"].shift(1)
    true_range = pd.concat([
        h4["high"] - h4["low"],
        (h4["high"] - previous_close).abs(),
        (h4["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)

    h4["atr14"] = true_range.rolling(
        ATR_PERIOD, min_periods=ATR_PERIOD
    ).mean()

    # Only completed 4H candles are made available to 15M candles.
    h4_ready = h4[["close", "ema50", "atr14"]].reset_index()
    h4_ready.columns = ["h4_close_time", "h4_close", "ema50", "atr14"]

    m15_ready = m15.reset_index()
    m15_ready.columns = [
        "bar_close_time", "open", "high", "low", "close", "volume"
    ]

    m15_ready = pd.merge_asof(
        m15_ready.sort_values("bar_close_time"),
        h4_ready.sort_values("h4_close_time"),
        left_on="bar_close_time",
        right_on="h4_close_time",
        direction="backward",
        allow_exact_matches=True,
    )

    return m15_ready


def confirmed_swings(bars, index):
    """Return the latest confirmed 2-left / 2-right swing levels."""
    latest_high = np.nan
    latest_low = np.nan

    # A swing centered at index-2 becomes confirmed at index.
    center = index - 2

    if center >= 2:
        window = bars.iloc[center - 2:center + 3]

        center_high = float(bars.iloc[center]["high"])
        center_low = float(bars.iloc[center]["low"])

        highs = window["high"].to_numpy(dtype=float)
        lows = window["low"].to_numpy(dtype=float)

        if center_high == max(highs) and np.sum(highs == center_high) == 1:
            latest_high = center_high

        if center_low == min(lows) and np.sum(lows == center_low) == 1:
            latest_low = center_low

    return latest_high, latest_low


def previous_day_levels(data):
    daily = data.groupby("date").agg(
        day_high=("high", "max"),
        day_low=("low", "min"),
    )

    daily["previous_high"] = daily["day_high"].shift(1)
    daily["previous_low"] = daily["day_low"].shift(1)

    return daily.to_dict("index")


def build_signals(data, m15):
    signals = []
    prior_levels = previous_day_levels(data)

    data = data.copy()
    data["clock"] = data["datetime"].dt.strftime("%H:%M")

    for trading_date, day in data.groupby("date", sort=True):
        if trading_date not in prior_levels:
            continue

        asian = day[
            (day["clock"] >= ASIAN_START)
            & (day["clock"] < ASIAN_END)
        ]

        if asian.empty:
            continue

        asian_high = float(asian["high"].max())
        asian_low = float(asian["low"].min())

        prev_high = prior_levels[trading_date]["previous_high"]
        prev_low = prior_levels[trading_date]["previous_low"]

        if pd.isna(prev_high) or pd.isna(prev_low):
            continue

        bars = m15[
            m15["bar_close_time"].dt.date == trading_date
        ].reset_index(drop=True)

        pending = None
        latest_swing_high = np.nan
        latest_swing_low = np.nan
        signal_created = False

        for i in range(len(bars)):
            row = bars.iloc[i]
            close_time = row["bar_close_time"]
            clock = close_time.strftime("%H:%M")

            if clock < ENTRY_START or clock > ENTRY_END:
                continue

            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])

            swing_high, swing_low = confirmed_swings(bars, i)

            if not np.isnan(swing_high):
                latest_swing_high = swing_high

            if not np.isnan(swing_low):
                latest_swing_low = swing_low

            # Require a completed 4H candle and a clear trend.
            h4_close = row["h4_close"]
            ema = row["ema50"]
            atr = row["atr14"]

            if pd.isna(h4_close) or pd.isna(ema) or pd.isna(atr):
                continue

            distance = abs(float(h4_close) - float(ema))
            if distance <= ATR_NEUTRAL_MULTIPLIER * float(atr):
                continue

            bias = "BUY" if h4_close > ema else "SELL"

            if signal_created:
                continue

            # Detect a sweep of Asian or previous-day liquidity.
            if pending is None:
                bearish_levels = [
                    level for level in [asian_high, float(prev_high)]
                    if high > level and close < level
                ]
                bullish_levels = [
                    level for level in [asian_low, float(prev_low)]
                    if low < level and close > level
                ]

                bearish_sweep = bool(bearish_levels)
                bullish_sweep = bool(bullish_levels)

                if bearish_sweep and bullish_sweep:
                    continue

                if bearish_sweep and bias == "SELL":
                    pending = {
                        "direction": "SELL",
                        "sweep_extreme": high,
                        "sweep_index": i,
                        "swept_levels": bearish_levels,
                    }

                elif bullish_sweep and bias == "BUY":
                    pending = {
                        "direction": "BUY",
                        "sweep_extreme": low,
                        "sweep_index": i,
                        "swept_levels": bullish_levels,
                    }

                continue

            # A later 15M close must confirm the market structure shift.
            if i <= pending["sweep_index"]:
                continue

            if pending["direction"] == "BUY":
                if (
                    bias == "BUY"
                    and not np.isnan(latest_swing_high)
                    and close > latest_swing_high
                ):
                    signals.append({
                        "date": trading_date,
                        "signal_time": close_time,
                        "direction": "BUY",
                        "sweep_extreme": pending["sweep_extreme"],
                        "mss_level": latest_swing_high,
                        "setup": "BULLISH_SWEEP_MSS",
                    })
                    signal_created = True

            elif pending["direction"] == "SELL":
                if (
                    bias == "SELL"
                    and not np.isnan(latest_swing_low)
                    and close < latest_swing_low
                ):
                    signals.append({
                        "date": trading_date,
                        "signal_time": close_time,
                        "direction": "SELL",
                        "sweep_extreme": pending["sweep_extreme"],
                        "mss_level": latest_swing_low,
                        "setup": "BEARISH_SWEEP_MSS",
                    })
                    signal_created = True

    return signals


def simulate():
    data = load_data().sort_values("datetime").reset_index(drop=True)
    m15 = build_timeframes(data)
    signals = build_signals(data, m15)

    signals_by_time = {
        signal["signal_time"]: signal for signal in signals
    }

    trades = []
    position = None
    daily_counts = {}
    daily_losses = {}
    equity = 0.0
    equity_peak = 0.0
    max_drawdown = 0.0

    def close_position(candle, exit_price, outcome):
        nonlocal position, equity, equity_peak, max_drawdown

        points = (
            exit_price - position["entry"]
            if position["direction"] == "BUY"
            else position["entry"] - exit_price
        )

        pnl = points * position["lots"] * DOLLARS_PER_POINT_PER_LOT
        equity += pnl
        equity_peak = max(equity_peak, equity)
        max_drawdown = max(max_drawdown, equity_peak - equity)

        trade = {
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
            "stop_points": position["risk_points"],
            "lots": position["lots"],
            "points": points,
            "pnl_usd": pnl,
            "outcome": outcome,
        }

        trades.append(trade)

        if outcome == "SL":
            daily_losses[position["date"]] = (
                daily_losses.get(position["date"], 0) + 1
            )

        position = None

    for _, candle in data.iterrows():
        timestamp = candle["datetime"]
        trading_date = candle["date"]
        clock = candle["time"]

        # Manage existing trades throughout the day.
        if position is not None:
            if trading_date != position["date"]:
                close_position(candle, float(candle["open"]), "DAY_END")
            else:
                high = float(candle["high"])
                low = float(candle["low"])
                open_price = float(candle["open"])

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

                if position is not None and clock >= DAY_END:
                    close_position(candle, float(candle["close"]), "DAY_END")

            # Do not open another trade on the same candle as an exit.
            if position is None:
                continue

            continue

        if clock < ENTRY_START or clock >= ENTRY_END:
            continue

        signal = signals_by_time.get(timestamp)
        if signal is None:
            continue

        count = daily_counts.get(trading_date, 0)
        losses = daily_losses.get(trading_date, 0)

        if count >= MAX_TRADES_PER_DAY or losses >= MAX_DAILY_LOSSES:
            continue

        entry = float(candle["open"])
        direction = signal["direction"]

        if direction == "BUY":
            stop = float(signal["sweep_extreme"]) - STOP_BUFFER_POINTS
            risk_points = entry - stop
            target = entry + REWARD_RISK * risk_points
        else:
            stop = float(signal["sweep_extreme"]) + STOP_BUFFER_POINTS
            risk_points = stop - entry
            target = entry - REWARD_RISK * risk_points

        if risk_points <= 0:
            continue

        lots = RISK_USD / (
            risk_points * DOLLARS_PER_POINT_PER_LOT
        )

        daily_counts[trading_date] = count + 1

        position = {
            "date": trading_date,
            "trade_number": count + 1,
            "setup": signal["setup"],
            "direction": direction,
            "entry_time": timestamp,
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk_points": risk_points,
            "lots": lots,
        }

    return {
        "trades": trades,
        "open_position": position,
        "signals": signals,
        "max_drawdown": max_drawdown,
        "daily_counts": daily_counts,
    }


if __name__ == "__main__":
    results = simulate()
    trades = results["trades"]

    print("LIQUIDITY SWEEP + MSS BACKTEST")
    print("Signals:", len(results["signals"]))
    print("Completed trades:", len(trades))
    print("Open position:", results["open_position"])

    if trades:
        wins = sum(t["outcome"] == "TP" for t in trades)
        losses = sum(t["outcome"] == "SL" for t in trades)
        day_end = sum(t["outcome"] == "DAY_END" for t in trades)
        pnl = sum(t["pnl_usd"] for t in trades)
        gross_profit = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
        gross_loss = abs(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

        print("Wins:", wins)
        print("Losses:", losses)
        print("Day-end exits:", day_end)
        print("Win rate (TP / completed trades):", round(wins / len(trades) * 100, 2), "%")
        print("Net P/L: $", round(pnl, 2))
        print("Profit factor:", round(profit_factor, 3))
        print("Maximum drawdown: $", round(results["max_drawdown"], 2))
        print("Average stop distance:", round(np.mean([t["stop_points"] for t in trades]), 2))

        print("\nLast 10 trades:")
        for trade in trades[-10:]:
            print(trade)
    else:
        print("No completed trades found.")
