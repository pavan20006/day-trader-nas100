from data_loader import load_data
from opening_range import calculate_opening_ranges
import config


def candle_touches(high, low, level):
    return low <= level <= high


def get_entry_price(candle, level, direction):
    open_price = float(candle["open"])

    if direction == "SELL" and open_price >= level:
        return open_price

    if direction == "BUY" and open_price <= level:
        return open_price

    return float(level)


def check_exit(position, candle):
    """Check SL/TP, including gaps. SL wins if both are touched."""

    high = float(candle["high"])
    low = float(candle["low"])
    open_price = float(candle["open"])

    direction = position["direction"]
    stop = position["stop"]
    target = position["target"]

    if direction == "BUY":
        if open_price <= stop:
            return open_price, "SL"
        if open_price >= target:
            return open_price, "TP"

        stop_hit = low <= stop
        target_hit = high >= target

    else:
        if open_price >= stop:
            return open_price, "SL"
        if open_price <= target:
            return open_price, "TP"

        stop_hit = high >= stop
        target_hit = low <= target

    if stop_hit:
        return stop, "SL"

    if target_hit:
        return target, "TP"

    return None, None


def check_entry_candle_stop(position, candle):
    """Conservative entry-candle rule: check SL, but never award TP."""
    high = float(candle["high"])
    low = float(candle["low"])
    direction = position["direction"]
    stop = position["stop"]

    if direction == "BUY" and low <= stop:
        return stop, "SL"

    if direction == "SELL" and high >= stop:
        return stop, "SL"

    return None, None


def simulate_all_days():
    """Simulate the strategy chronologically, including overnight positions."""

    data = load_data().sort_values("datetime").reset_index(drop=True)
    opening_ranges = calculate_opening_ranges()

    ranges_by_date = {
        row["date"]: row
        for row in opening_ranges
    }

    daily_states = {}
    trades = []
    position = None

    def get_daily_state(trading_date):
        if trading_date not in daily_states:
            daily_states[trading_date] = {
                "state": "initial",
                "trades": [],
                "confirmation_level": None,
            }
        return daily_states[trading_date]

    def record_closed_trade(candle, exit_price, outcome):
        nonlocal position

        direction = position["direction"]

        if direction == "BUY":
            points = exit_price - position["entry"]
        else:
            points = position["entry"] - exit_price

        pnl = (
            points
            * config.POSITION_SIZE_LOTS
            * config.DOLLARS_PER_POINT_PER_LOT
        )

        trade = {
            "date": position["strategy_date"],
            "trade_number": position["trade_number"],
            "setup": position["setup"],
            "direction": direction,
            "entry_time": position["entry_time"],
            "exit_time": candle["datetime"],
            "entry": position["entry"],
            "exit": float(exit_price),
            "stop_loss": position["stop"],
            "take_profit": position["target"],
            "points": points,
            "pnl_usd": pnl,
            "outcome": outcome,
        }

        trades.append(trade)

        day_state = get_daily_state(position["strategy_date"])
        day_state["trades"].append(trade)

        if len(day_state["trades"]) >= config.MAX_TRADES_PER_DAY:
            day_state["state"] = "done"
        elif outcome == "SL":
            day_state["state"] = "retest"
        elif outcome == "TP":
            day_state["state"] = "done"
        else:
            day_state["state"] = "done"

        position = None

    for _, candle in data.iterrows():
        current_date = candle["date"]
        current_time = candle["time"]

        high = float(candle["high"])
        low = float(candle["low"])

        # Manage an existing position on every available candle,
        # including after 12:30 PM and on subsequent trading days.
        if position is not None:
            exit_price, outcome = check_exit(position, candle)

            if outcome is not None:
                record_closed_trade(candle, exit_price, outcome)

            # Never open another position on the same candle as an exit.
            continue

        # New entries are allowed only during the entry window.
        if not (
            config.TRADING_START <= current_time < config.TRADING_END
        ):
            continue

        if current_date not in ranges_by_date:
            continue

        day_state = get_daily_state(current_date)

        if day_state["state"] == "done":
            continue

        if len(day_state["trades"]) >= config.MAX_TRADES_PER_DAY:
            continue

        opening_range = ranges_by_date[current_date]
        or_high = float(opening_range["or_high"])
        or_low = float(opening_range["or_low"])

        state = day_state["state"]

        if state == "initial":
            upper_touched = high >= or_high
            lower_touched = low <= or_low
            close_price = float(candle["close"])

            if upper_touched and lower_touched:
                continue

            if upper_touched and close_price < or_high:
                day_state["state"] = "await_sell_break"
                day_state["confirmation_level"] = low
                continue

            elif lower_touched and close_price > or_low:
                day_state["state"] = "await_buy_break"
                day_state["confirmation_level"] = high
                continue

            else:
                continue

        elif state == "await_sell_break":
            trigger = day_state["confirmation_level"]

            if low > trigger:
                continue

            direction = "SELL"
            entry = get_entry_price(candle, trigger, direction)
            setup = "ORH_REJECTION_SELL"

        elif state == "await_buy_break":
            trigger = day_state["confirmation_level"]

            if high < trigger:
                continue

            direction = "BUY"
            entry = get_entry_price(candle, trigger, direction)
            setup = "ORL_REJECTION_BUY"

        elif state == "retest":
            first_trade = day_state["trades"][0]
            retest_price = first_trade["entry"]

            if not candle_touches(high, low, retest_price):
                continue

            direction = (
                "BUY" if first_trade["direction"] == "SELL" else "SELL"
            )
            entry = get_entry_price(candle, retest_price, direction)
            setup = "REVERSAL_AFTER_SL"

        elif state == "boundary":
            continue  # Experimental: disable second boundary trades
            upper_touched = high >= or_high
            lower_touched = low <= or_low

            if upper_touched and lower_touched:
                continue

            if upper_touched:
                direction = "SELL"
                entry = get_entry_price(candle, or_high, direction)
                setup = "SECOND_TRADE_ORH"

            elif lower_touched:
                direction = "BUY"
                entry = get_entry_price(candle, or_low, direction)
                setup = "SECOND_TRADE_ORL"

            else:
                continue

        else:
            continue

        if direction == "BUY":
            stop = entry - config.STOP_LOSS_POINTS
            target = entry + config.TAKE_PROFIT_POINTS
        else:
            stop = entry + config.STOP_LOSS_POINTS
            target = entry - config.TAKE_PROFIT_POINTS

        position = {
            "strategy_date": current_date,
            "trade_number": len(day_state["trades"]) + 1,
            "direction": direction,
            "entry": entry,
            "entry_time": candle["datetime"],
            "stop": stop,
            "target": target,
            "setup": setup,
        }

        # On the entry candle, check SL only.
        # A TP on this candle cannot be confirmed with OHLC data.
        exit_price, outcome = check_entry_candle_stop(position, candle)

        if outcome == "SL":
            record_closed_trade(candle, exit_price, outcome)

    return {
        "trades": trades,
        "open_position": position,
        "daily_states": daily_states,
    }


if __name__ == "__main__":
    results = simulate_all_days()
    trades = results["trades"]

    print("MULTI-DAY NAS100 SIMULATOR: SUCCESS")
    print("Completed trades:", len(trades))
    print("Open position at end of data:", results["open_position"])

    if trades:
        total_pnl = sum(trade["pnl_usd"] for trade in trades)
        print("Total P/L: $", round(total_pnl, 2))
        print("SL exits:", sum(t["outcome"] == "SL" for t in trades))
        print("TP exits:", sum(t["outcome"] == "TP" for t in trades))

        print("\nLast five completed trades:")
        for trade in trades[-5:]:
            print(trade)

