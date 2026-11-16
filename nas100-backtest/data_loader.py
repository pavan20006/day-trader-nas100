from pathlib import Path

import pandas as pd

import config


def load_data():
    """Load and validate NAS100 one-minute historical data."""

    project_dir = Path(__file__).resolve().parent
    csv_path = project_dir / config.DATA_FILE

    if not csv_path.exists():
        raise FileNotFoundError(f"Historical data not found: {csv_path}")

    df = pd.read_csv(csv_path)

    required = ["datetime", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in df.columns]

    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df[required].copy()

    df["datetime"] = pd.to_datetime(
        df["datetime"], utc=True, errors="coerce"
    )

    if df["datetime"].isna().any():
        raise ValueError("Invalid or missing timestamps found.")

    price_columns = ["open", "high", "low", "close", "volume"]

    for column in price_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if df[price_columns].isna().any().any():
        raise ValueError("Invalid or missing numeric values found.")

    if (df["volume"] < 0).any():
        raise ValueError("Negative volume found.")

    invalid_ohlc = (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    )

    if invalid_ohlc.any():
        raise ValueError(
            f"Invalid OHLC candles found: {int(invalid_ohlc.sum())}"
        )

    if df["datetime"].duplicated().any():
        raise ValueError("Duplicate timestamps found.")

    df = df.sort_values("datetime").reset_index(drop=True)

    df["datetime"] = df["datetime"].dt.tz_convert(config.TIMEZONE)
    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.strftime("%H:%M")

    return df


if __name__ == "__main__":
    data = load_data()

    print("NAS100 DATA LOADER: SUCCESS")
    print("Total candles:", len(data))
    print("Trading dates:", data["date"].nunique())
    print("First timestamp:", data["datetime"].iloc[0])
    print("Last timestamp:", data["datetime"].iloc[-1])
    print("Timezone:", data["datetime"].dt.tz)
