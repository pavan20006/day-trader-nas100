"""Validation helpers for the NAS100 opening-range backtest.

This module is intentionally independent of the simulators. It checks baseline
configuration, OHLCV input and completed-trade ledger consistency. It does not
change any strategy entry or exit decisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Mapping, Sequence

import pandas as pd


REQUIRED_OHLCV = ("datetime", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class StrategyConfig:
    """The documented baseline; monetary sizing is derived from point value."""

    opening_range_start: str = "09:30"
    opening_range_end: str = "10:30"
    entry_window_start: str = "10:30"
    entry_window_end: str = "12:30"
    stop_loss_points: float = 20.0
    take_profit_points: float = 40.0
    risk_usd: float = 75.0
    reward_usd: float = 150.0
    dollars_per_point_per_lot: float = 1.0
    max_trades_per_day: int = 2

    @property
    def position_size_lots(self) -> float:
        if self.stop_loss_points <= 0 or self.dollars_per_point_per_lot <= 0:
            raise ValueError("Stop distance and point value must be positive.")
        return self.risk_usd / (
            self.stop_loss_points * self.dollars_per_point_per_lot
        )

    def validate(self) -> None:
        for name in (
            "stop_loss_points",
            "take_profit_points",
            "risk_usd",
            "reward_usd",
            "dollars_per_point_per_lot",
        ):
            if getattr(self, name) <= 0:
                raise ValueError("{} must be positive.".format(name))

        if self.max_trades_per_day != 2:
            raise ValueError("Baseline strategy allows exactly two trades per day.")
        if not math.isclose(
            self.take_profit_points, 2 * self.stop_loss_points, rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError("Baseline target must be twice the stop distance.")
        if not math.isclose(
            self.reward_usd, 2 * self.risk_usd, rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError("Baseline monetary target must be twice monetary risk.")

        for name in (
            "opening_range_start",
            "opening_range_end",
            "entry_window_start",
            "entry_window_end",
        ):
            try:
                datetime.strptime(getattr(self, name), "%H:%M")
            except ValueError:
                raise ValueError("{} must use HH:MM format.".format(name))

        if self.opening_range_start >= self.opening_range_end:
            raise ValueError("Opening-range start must precede its end.")
        if self.entry_window_start >= self.entry_window_end:
            raise ValueError("Entry-window start must precede its end.")


def validate_ohlcv(frame: pd.DataFrame) -> List[str]:
    """Return data-quality errors; an empty list means the frame passes checks.

    The timestamps must be timezone-aware, unique and strictly ascending.
    Session gaps are allowed: weekends, holidays and closed market hours are
    not treated as missing one-minute candles.
    """
    errors = []
    missing = [column for column in REQUIRED_OHLCV if column not in frame.columns]
    if missing:
        return ["Missing required columns: " + ", ".join(missing)]
    if frame.empty:
        return ["No candle rows supplied."]

    timestamps = pd.to_datetime(frame["datetime"], errors="coerce")
    if timestamps.isna().any():
        errors.append("datetime contains invalid or missing values.")
    else:
        try:
            timezone = timestamps.dt.tz
        except AttributeError:
            timezone = None
        if timezone is None:
            errors.append("datetime must be timezone-aware.")
        else:
            if timestamps.duplicated().any():
                errors.append("Duplicate candle timestamps found.")
            if not timestamps.is_monotonic_increasing:
                errors.append("Candle timestamps are not sorted ascending.")

    numeric = frame[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric.isna().any().any():
        errors.append("OHLCV contains missing or non-numeric values.")
        return errors

    if not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()):
        errors.append("OHLCV contains infinite values.")
        return errors

    if (numeric["volume"] < 0).any():
        errors.append("Negative volume found.")

    invalid = (
        (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        errors.append("Invalid OHLC candle bounds: {} row(s).".format(int(invalid.sum())))

    if not (numeric[["open", "high", "low", "close"]] > 0).all().all():
        errors.append("OHLC prices must be positive.")

    return errors


def validate_trade_ledger(
    trades: Sequence[Mapping[str, object]],
    max_trades_per_day: int = 2,
) -> List[str]:
    """Check ledger arithmetic and per-day trade-count limits."""
    errors = []
    counts = {}
    required = {
        "date",
        "trade_number",
        "direction",
        "entry",
        "exit",
        "stop_loss",
        "take_profit",
        "points",
        "pnl_usd",
        "outcome",
    }

    if max_trades_per_day < 1:
        return ["max_trades_per_day must be at least one."]

    for index, trade in enumerate(trades):
        missing = required.difference(trade)
        if missing:
            errors.append(
                "Trade {}: missing fields {}.".format(
                    index, ", ".join(sorted(missing))
                )
            )
            continue

        day = trade["date"]
        counts[day] = counts.get(day, 0) + 1
        if counts[day] > max_trades_per_day:
            errors.append("{}: exceeds {} trades.".format(day, max_trades_per_day))

        direction = trade["direction"]
        if direction not in ("BUY", "SELL"):
            errors.append("Trade {}: invalid direction.".format(index))
            continue

        try:
            entry = float(trade["entry"])
            exit_price = float(trade["exit"])
            stop = float(trade["stop_loss"])
            target = float(trade["take_profit"])
            points = float(trade["points"])
            pnl = float(trade["pnl_usd"])
        except (TypeError, ValueError):
            errors.append("Trade {}: non-numeric price/P&L field.".format(index))
            continue

        if not all(
            math.isfinite(value)
            for value in (entry, exit_price, stop, target, points, pnl)
        ):
            errors.append("Trade {}: non-finite numeric value.".format(index))
            continue

        expected_points = exit_price - entry
        if direction == "SELL":
            expected_points = -expected_points
        if not math.isclose(points, expected_points, rel_tol=0, abs_tol=1e-8):
            errors.append("Trade {}: points do not reconcile with entry/exit.".format(index))

        if trade["outcome"] not in ("SL", "TP", "DAY_END"):
            errors.append("Trade {}: unknown outcome {!r}.".format(index, trade["outcome"]))

        if direction == "BUY" and not (stop < entry < target):
            errors.append("Trade {}: BUY stop/entry/target ordering is invalid.".format(index))
        if direction == "SELL" and not (target < entry < stop):
            errors.append("Trade {}: SELL stop/entry/target ordering is invalid.".format(index))

    return errors
