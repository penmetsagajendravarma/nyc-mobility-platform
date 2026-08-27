"""
TLC yellow taxi ingestion.

Reads a monthly parquet file, normalises column names, drops impossible
records, and loads into raw.yellow_trips. Safe to rerun: a file that has
already loaded successfully is skipped.
"""

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql+psycopg2://analytics:analytics@localhost:5433/nyc_mobility"
DATA_DIR = "data/raw"

COLUMN_MAP = {
    "VendorID":              "vendor_id",
    "tpep_pickup_datetime":  "pickup_datetime",
    "tpep_dropoff_datetime": "dropoff_datetime",
    "passenger_count":       "passenger_count",
    "trip_distance":         "trip_distance",
    "RatecodeID":            "ratecode_id",
    "store_and_fwd_flag":    "store_and_fwd_flag",
    "PULocationID":          "pickup_location_id",
    "DOLocationID":          "dropoff_location_id",
    "payment_type":          "payment_type",
    "fare_amount":           "fare_amount",
    "extra":                 "extra",
    "mta_tax":               "mta_tax",
    "tip_amount":            "tip_amount",
    "tolls_amount":          "tolls_amount",
    "improvement_surcharge": "improvement_surcharge",
    "total_amount":          "total_amount",
    "congestion_surcharge":  "congestion_surcharge",
    "Airport_fee":           "airport_fee",
    "cbd_congestion_fee":    "cbd_congestion_fee",
}


def transform(df, year, month):
    """Rename columns, add the payment-detail flag, drop impossible rows."""

    # Fail loudly if the file has columns we don't know about.
    unexpected = set(df.columns) - set(COLUMN_MAP)
    if unexpected:
        raise ValueError(f"Unmapped columns: {unexpected}")

    df = df.rename(columns=COLUMN_MAP)

    # D-005: payment_type 0 marks the block with five null payment/vehicle
    # fields. Flag it rather than dropping 15% of trips.
    df["has_payment_detail"] = df["payment_type"] != 0

    before = len(df)

    # Impossible records only. Anything questionable stays and gets handled
    # in dbt, where the logic is versioned and testable.
    df = df[df["dropoff_datetime"] > df["pickup_datetime"]]

    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end = month_start + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1)
    df = df[(df["pickup_datetime"] >= month_start) &
            (df["pickup_datetime"] < month_end)]

    print(f"  dropped {before - len(df):,} impossible rows")
    return df


def already_loaded(engine, file_key):
    """True if this file has already been loaded successfully."""
    q = text("""
        SELECT 1 FROM meta.ingestion_log
        WHERE source = 'yellow' AND file_key = :k AND status = 'success'
    """)
    with engine.connect() as conn:
        return conn.execute(q, {"k": file_key}).first() is not None


def load_month(engine, year, month):
    """Load one month of yellow taxi data into raw.yellow_trips."""
    file_key = f"yellow_tripdata_{year}-{month:02d}"

    if already_loaded(engine, file_key):
        print(f"{file_key}: already loaded, skipping")
        return

    print(f"{file_key}: reading...")
    df = pd.read_parquet(f"{DATA_DIR}/{file_key}.parquet")
    rows_read = len(df)
    print(f"  {rows_read:,} rows read")

    df = transform(df, year, month)
    rows_loaded = len(df)

    print(f"  writing {rows_loaded:,} rows to raw.yellow_trips...")
    df.to_sql(
        "yellow_trips",
        engine,
        schema="raw",
        if_exists="append",
        index=False,
        chunksize=50_000,
        method="multi",
    )

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO meta.ingestion_log
                (source, file_key, rows_read, rows_loaded, rows_rejected,
                 status, completed_at)
            VALUES
                ('yellow', :k, :read, :loaded, :rejected, 'success', now())
        """), {
            "k": file_key,
            "read": rows_read,
            "loaded": rows_loaded,
            "rejected": rows_read - rows_loaded,
        })

    print("  done\n")


if __name__ == "__main__":
    engine = create_engine(DB_URL)
    load_month(engine, 2025, 1)