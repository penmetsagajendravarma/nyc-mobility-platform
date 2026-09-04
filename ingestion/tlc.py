"""
TLC yellow taxi ingestion.

Reads a monthly parquet file, normalises column names, drops impossible
records, and loads into raw.yellow_trips. Safe to rerun: a file that has
already loaded successfully is skipped.

Loading uses Postgres COPY rather than INSERT batches. COPY streams raw CSV
straight into the table with no per-statement parsing, which is roughly an
order of magnitude faster at this row count.
"""

import io
import time

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

    # Fail loudly on columns we don't know about. Missing columns are fine —
    # TLC adds fields over time (cbd_congestion_fee appears from Jan 2025,
    # when congestion pricing began) — but unknown ones mean the schema moved
    # under us and the map needs updating.
    unexpected = set(df.columns) - set(COLUMN_MAP)
    if unexpected:
        raise ValueError(f"Unmapped columns: {unexpected}")

    missing = set(COLUMN_MAP) - set(df.columns)
    if missing:
        print(f"  note: columns absent in this file: {sorted(missing)}")

    df = df.rename(columns=COLUMN_MAP)

    # Add any absent columns as null so every month has the same shape.
    for src, dest in COLUMN_MAP.items():
        if dest not in df.columns:
            df[dest] = pd.NA

    # D-005: payment_type 0 marks the block with five null payment/vehicle
    # fields. Flag it rather than dropping 15% of trips.
    df["has_payment_detail"] = df["payment_type"] != 0

    before = len(df)

    df = df[df["dropoff_datetime"] > df["pickup_datetime"]]

    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end = month_start + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1)
    df = df[(df["pickup_datetime"] >= month_start) &
            (df["pickup_datetime"] < month_end)]

    print(f"  dropped {before - len(df):,} impossible rows")
    return df


def copy_into_postgres(df, engine, schema, table):
    """Bulk load a dataframe using Postgres COPY. Returns elapsed seconds."""
    t0 = time.time()

    # COPY requires the table to exist; it will not create one.
    df.head(0).to_sql(table, engine, schema=schema,
                      if_exists="append", index=False)

    # COPY matches columns by POSITION, not name. Read the table's actual
    # column order and reorder the dataframe to match, then name the columns
    # explicitly in the COPY statement so the mapping is unambiguous.
    with engine.connect() as conn:
        cols = [r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = :s AND table_name = :t
            ORDER BY ordinal_position
        """), {"s": schema, "t": table})]

    df = df[cols]
    col_list = ", ".join(f'"{c}"' for c in cols)

    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            cur.copy_expert(
                f"COPY {schema}.{table} ({col_list}) "
                f"FROM STDIN WITH (FORMAT csv, NULL '\\N')",
                buf,
            )
        raw_conn.commit()
    finally:
        raw_conn.close()

    return time.time() - t0


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
    elapsed = copy_into_postgres(df, engine, "raw", "yellow_trips")
    print(f"  loaded in {elapsed:.1f}s "
          f"({rows_loaded / elapsed:,.0f} rows/sec)")

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
    load_month(engine, 2024, 11)
    load_month(engine, 2024, 12)
    load_month(engine, 2025, 1)
    load_month(engine, 2025, 2)
