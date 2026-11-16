from data_loader import load_data
import config


def calculate_opening_ranges():
    data = load_data()

    opening_data = data[
        (data["time"] >= config.OR_START)
        & (data["time"] < config.OR_END)
    ]

    results = []

    for trading_date, candles in opening_data.groupby("date"):
        if len(candles) != 60:
            continue

        results.append({
            "date": trading_date,
            "or_high": float(candles["high"].max()),
            "or_low": float(candles["low"].min()),
            "or_range": float(
                candles["high"].max() - candles["low"].min()
            ),
            "candle_count": len(candles),
        })

    return results


if __name__ == "__main__":
    ranges = calculate_opening_ranges()

    print("OPENING RANGE CALCULATOR: SUCCESS")
    print("Complete opening ranges:", len(ranges))
    print("Expected candles per range: 60")

    print("\nFIRST 5 OPENING RANGES:")
    for item in ranges[:5]:
        print(item)

    print("\nLAST 3 OPENING RANGES:")
    for item in ranges[-3:]:
        print(item)
