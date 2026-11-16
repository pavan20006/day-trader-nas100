"""Validation helpers for the NAS100 opening-range backtest.

This module is deliberately independent of the existing simulators. It checks
configuration invariants and candle data before a backtest is run. It does not
alter entries, exits, or trading rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import pandas as pd


REQUIRED_OHLCV = ("datetime", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class StrategyConfig:
    """Explicit baseline settings; monetary sizing is derived, not guessed."""

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
            "stop_loss_points", "take_profit_points", "risk_usd",
            "reward_usd", "dollars_per_point_per_lot",
        ):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        if self.max_trades_per_day != 2:
            raise ValueError("Baseline strategy allows exactly two trades per day.")
        if self.take_profit_points != 2 * self.stop_loss_points:
            raise ValueError("Baseline target must be twice the stop distance.")
        if self.reward_usd != 2 * self.risk_usd:
            raise ValueError("Baseline monetary target must be twice monetary risk.")
        if self.opening_range_start >= self.opening_range_end:
            raise ValueError("Opening-range start must precede its end.")
        if self.entry_window_start >= self.entry_window_end:
            raise ValueError("Entry-window start must precede its end.")


def validate_ohlcv(
    frame: pd.DataFrame,
    expected_interval_minutes: int | None = 1,
) -> list[str]:
    """Return validation errors for an OHLCV frame; empty means valid.

    Datetimes must be timezone-aware, unique and increasing. A missing minute
    is reported as a warning/error only when a one-minute interval is expected;
    market holidays and overnight gaps should be validated per session by the
    caller, not treated as continuous data.
    """
    errors: list[str] = []
    missing = [column for column in REQUIRED_OHLCV if column not in frame.columns]
    if missing:
        return ["Missing required columns: " + ", ".join(missing)]

    if frame.empty:
        return ["No candle rows supplied."]

    timestamps = pd.to_datetime(frame["datetime"], errors="coerce")
    if timestamps.isna().any():
        errors.append("datetime contains invalid or missing values.")
    elif timestamps.dt.tz is None:
        errors.append("datetime must be timezone-aware.")
    else:
        if timestamps.duplicated().any():
            errors.append("Duplicate candle timestamps found.")
        if not timestamps.is_monotonic_increasing:
            errors.append("Candle timestamps are not sorted ascending.")
        if expected_interval_minutes is not None and len(timestamps) > 1:
            # Only flag backwards/duplicate gaps here. Session gaps are normal.
            diffs = timestamps.diff().dropna()
            if (diffs <= pd.Timedelta(0)).any():
                errors.append("Candle timestamps must be strictly increasing.")

    numeric = frame[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric.isna().any().any():
        errors.append("OHLCV contains missing or non-numeric values.")
        return errors

    if (numeric["volume"] < 0).any():
        errors.append("Negative volume found.")

    invalid = (
        (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        errors.append(f"Invalid OHLC candle bounds: {int(invalid.sum())} row(s).")

    if not (numeric[["open", "high", "low", "close"]] > 0).all().all():
        errors.append("OHLC prices must be positive.")

    return errors


def validate_trade_ledger(
    trades: Sequence[Mapping[str, object]],
    max_trades_per_day: int = 2,
) -> list[str]:
    """Check ledger invariants without deciding whether trades are profitable."""
    errors: list[str] = []
    counts: dict[object, int] = {}
    required = {
        "date", "trade_number", "direction", "entry", "exit",
        "stop_loss", "take_profit", "points", "pnl_usd", "outcome",
    }

    for index, trade in enumerate(trades):
        missing = required.difference(trade)
        if missing:
            errors.append(
                f"Trade {index}: missing fields {', '.join(sorted(missing))}."
            )
            continue

        day = trade["date"]
        counts[day] = counts.get(day, 0) + 1
        if counts[day] > max_trades_per_day:
            errors.append(f"{day}: exceeds {max_trades_per_day} trades.")

        if trade["direction"] not in ("BUY", "SELL"):
            errors.append(f"Trade {index}: invalid direction.")
            continue

        try:
            entry = float(trade["entry"])
            exit_price = float(trade["exit"])
            stop = float(trade["stop_loss"])
            target = float(trade["take_profit"])
            points = float(trade["points"])
            pnl = float(trade["pnl_usd"])
        except (TypeError, ValueError):
            errors.append(f"Trade {index}: non-numeric price/P&L field.")
            continue

        expected_points = exit_price - entry
        if trade["direction"] == "SELL":
            expected_points = -expected_points
        if abs(points - expected_points) > 1e-8:
            errors.append(f"Trade {index}: points do not reconcile with entry/exit.")

        if trade["outcome"] not in ("SL", "TP", "DAY_END"):
            errors.append(f"Trade {index}: unknown outcome {trade['outcome']!r}.")

        if trade["direction"] == "BUY" and not (stop < entry < target):
            errors.append(f"Trade {index}: BUY stop/entry/target ordering is invalid.")
        if trade["direction"] == "SELL" and not (target < entry < stop):
            errors.append(f"Trade {index}: SELL stop/entry/target ordering is invalid.")

        if not all(map(lambda x: abs(x) < float("inf"), (entry, exit_price, stop, target, points, pnl))):
            errors.append(f"Trade {index}: non-finite numeric value.")

    return errors
