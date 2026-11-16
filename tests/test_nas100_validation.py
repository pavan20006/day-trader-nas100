"""Unit tests for the isolated NAS100 validation layer."""

import os
import sys
import unittest

import pandas as pd

BACKTEST_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "nas100-backtest")
)
if BACKTEST_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_DIR)

import config
from validation import StrategyConfig, validate_ohlcv, validate_trade_ledger


class StrategyConfigTests(unittest.TestCase):
    def test_baseline_matches_user_risk_and_reward(self):
        baseline = StrategyConfig()
        baseline.validate()
        self.assertEqual(baseline.stop_loss_points, 20.0)
        self.assertEqual(baseline.take_profit_points, 40.0)
        self.assertEqual(baseline.risk_usd, 75.0)
        self.assertEqual(baseline.reward_usd, 150.0)
        self.assertEqual(baseline.max_trades_per_day, 2)
        self.assertAlmostEqual(baseline.position_size_lots, 3.75)

    def test_repository_config_has_same_monetary_baseline(self):
        self.assertEqual(config.RISK_PER_TRADE_USD, 75.0)
        self.assertEqual(config.TARGET_PROFIT_USD, 150.0)
        self.assertEqual(config.STOP_LOSS_POINTS, 20.0)
        self.assertEqual(config.TAKE_PROFIT_POINTS, 40.0)
        self.assertEqual(config.MAX_TRADES_PER_DAY, 2)
        self.assertAlmostEqual(config.POSITION_SIZE_LOTS, 3.75)

    def test_rejects_non_two_trade_limit(self):
        invalid = StrategyConfig(max_trades_per_day=3)
        with self.assertRaises(ValueError):
            invalid.validate()


class OhlcvValidationTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "datetime": pd.to_datetime(
                ["2026-01-05T14:30:00Z", "2026-01-05T14:31:00Z"]
            ),
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [10.0, 12.0],
        })

    def test_accepts_valid_timezone_aware_ohlcv(self):
        self.assertEqual(validate_ohlcv(self.frame), [])

    def test_rejects_missing_columns(self):
        errors = validate_ohlcv(self.frame.drop(columns=["volume"]))
        self.assertTrue(any("Missing required columns" in item for item in errors))

    def test_rejects_naive_timestamps(self):
        frame = self.frame.copy()
        frame["datetime"] = frame["datetime"].dt.tz_localize(None)
        errors = validate_ohlcv(frame)
        self.assertTrue(any("timezone-aware" in item for item in errors))

    def test_rejects_duplicate_timestamps(self):
        frame = self.frame.copy()
        frame.loc[1, "datetime"] = frame.loc[0, "datetime"]
        errors = validate_ohlcv(frame)
        self.assertTrue(any("Duplicate" in item for item in errors))

    def test_rejects_invalid_ohlc_bounds(self):
        frame = self.frame.copy()
        frame.loc[0, "high"] = 98.0
        errors = validate_ohlcv(frame)
        self.assertTrue(any("Invalid OHLC" in item for item in errors))

    def test_rejects_negative_volume(self):
        frame = self.frame.copy()
        frame.loc[0, "volume"] = -1
        errors = validate_ohlcv(frame)
        self.assertTrue(any("Negative volume" in item for item in errors))


class TradeLedgerValidationTests(unittest.TestCase):
    def setUp(self):
        self.trade = {
            "date": "2026-01-05",
            "trade_number": 1,
            "direction": "BUY",
            "entry": 100.0,
            "exit": 140.0,
            "stop_loss": 80.0,
            "take_profit": 140.0,
            "points": 40.0,
            "pnl_usd": 150.0,
            "outcome": "TP",
        }

    def test_accepts_reconciled_trade(self):
        self.assertEqual(validate_trade_ledger([self.trade]), [])

    def test_rejects_incorrect_points(self):
        trade = dict(self.trade, points=39.0)
        errors = validate_trade_ledger([trade])
        self.assertTrue(any("do not reconcile" in item for item in errors))

    def test_rejects_more_than_two_trades_per_day(self):
        trades = [dict(self.trade, trade_number=i) for i in (1, 2, 3)]
        errors = validate_trade_ledger(trades, max_trades_per_day=2)
        self.assertTrue(any("exceeds 2 trades" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
