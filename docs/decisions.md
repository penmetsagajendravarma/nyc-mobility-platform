# Decisions Log

Every non-obvious choice made in this project, with the reasoning behind it.

---

## D-001 — Postgres over DuckDB or BigQuery

**Decided:** local Postgres in Docker.

**Why:** dbt targets it cleanly, it mirrors what a small data team actually runs,
and the whole stack stays reproducible via docker-compose.

---

## D-002 — Ingestion writes only to `raw`

**Decided:** the ingestion layer normalises column names and loads. No business
logic.

**Why:** a logic change becomes a dbt model edit and a rerun, not a full
re-download.

---

## D-003 — Rejected rows are quarantined, not dropped

**Decided:** invalid rows go to a rejects table with a reason tag.

**Why:** silent drops hide data quality problems. "N rows rejected, here's the
breakdown" is the finding.

---

## D-004 — Column naming convention

TODO — decided during ingestion implementation.

The source file uses four different naming conventions in one schema:
`VendorID`, `tpep_pickup_datetime`, `PULocationID`, `Airport_fee`,
`cbd_congestion_fee`.

Questions to answer here:
- What convention did you standardise on, and why?
- What did you do with columns not in the mapping?
- Did column names differ across months, and how did you handle that?

---

## D-005 — Handling of the payment_type = 0 record block

**Observed (January 2025 yellow taxi, 3,475,226 rows):**

| Check | Count | % |
|---|---|---|
| Dropoff before pickup | 124 | 0.004% |
| Zero-length trips | 1,927 | 0.055% |
| Pickup outside January 2025 | 22 | 0.001% |
| Negative fare | 144,118 | 4.147% |
| Zero fare | 1,398 | 0.040% |
| Negative total | 63,037 | 1.814% |
| Zero distance | 90,893 | 2.615% |
| Distance > 100 miles | 162 | 0.005% |
| passenger_count null | 540,149 | 15.543% |
| passenger_count = 0 | 24,656 | 0.709% |
| Invalid pickup/dropoff zone | 0 | 0.000% |

**Finding:** the null passenger_count count (540,149) is identical to the count
of rows with `payment_type = 0`. These are the same rows. Five columns are null
together across the entire group and never partially: `passenger_count`,
`RatecodeID`, `store_and_fwd_flag`, `congestion_surcharge`, `Airport_fee`.

Outside this group the file contains **zero nulls** in any column.

**Additional characteristics:**
- Spans all three vendors: 451,456 (vendor 2), 88,204 (vendor 1), 489 (vendor 6)
- Vendor 6 and payment_type 0 are both undocumented in the TLC data dictionary
- Covers the full month, not a single bad day
- Median trip distance 2.04 mi vs 1.60 mi for healthy rows — plausible trips
- Contains impossible distances (max 276,423 mi), inflating std dev to 1,428

**Interpretation:** a schema mismatch, not data entry error. A source system
that does not carry payment and vehicle fields is being merged into the same
file. The trips themselves appear real; only the payment metadata is absent.

**Decision:**
- Keep these rows. Deleting 15.5% of trips to fix missing payment fields would
  distort demand and volume analysis, which does not depend on those fields.
- Add a boolean flag `has_payment_detail` so the exclusion is explicit
  downstream rather than buried in a WHERE clause.
- Exclude the group from revenue, tipping, and payment-type analysis.
- Apply distance bounds independently (see D-007).

**Rejected:** dropping the rows entirely (loses real trips); imputing
passenger_count (invents data, and the field is missing structurally rather
than at random).

---

## D-006 — Negative fares

**Observed:** 144,118 rows with `fare_amount < 0`, all from vendor 2.
Two distinct populations:

**(a) ~62,700 rows, payment types 2/3/4.** The whole record is negated — e.g.
fare -7.20 with total -8.54. Components sum correctly to the negated total. The
25th and 75th percentiles are both -4.75, indicating repeated identical values.

Reading: reversal entries. The system logs a cancellation by rewriting the
original trip with flipped signs.

**(b) 81,402 rows with negative fare but non-negative total.** 81,401 of these
carry `payment_type = 0` and fall in the block described in D-005. Components do
not reconcile — e.g. distance 7.30 mi, fare -0.47, no extras, no tolls,
total 3.53.

Reading: the fare field in this group does not contain a fare. Corrupted, not a
business event.

**Decision:**
- Group (a): retain. Exclude from trip counts (cancellations, not rides) but
  include in revenue aggregates (the refund genuinely reduced revenue).
- Group (b): falls under the D-005 rule — payment fields unusable, trip retained.

**Caveat:** the reversal interpretation for group (a) is inferred from a sample
of ten rows. Verify that negated components reconcile to the negated total
across the full group before relying on it.

---

## D-007 — Distance bounds

TODO — decide after profiling the distance distribution.

Known: max observed distance is 276,423 miles, which is impossible. The
`payment_type = 0` group carries most of the extreme values (std dev 1,428 vs
42 for healthy rows).

Questions to answer:
- What upper bound, and what is the justification for that specific number?
- How many rows does it exclude?
- Are zero-distance trips (90,893) valid? A passenger entering and immediately
  leaving is a real event.