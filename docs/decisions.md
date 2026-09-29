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

---

## D-008 — Undocumented payment_type = 5

**Found by test, not inspection.** An `accepted_values` test on `payment_type`
failed against the full four-month dataset.

| payment_type | Rows |
|---|---|
| 0 (undocumented) | 2,046,252 |
| 1 (card) | 10,226,079 |
| 2 (cash) | 1,667,947 |
| 3 (no charge) | 101,050 |
| 4 (dispute) | 315,744 |
| **5 (unknown)** | **1** |

One row in 14,357,073. TLC documents type 5 as "unknown."

**Decision:** added 5 to the accepted values. Retained the row.

**Also noted:** the `payment_type = 0` block described in D-005 is **2,046,252
rows across four months (14.3%)**, not a January anomaly. It appears at a
consistent rate in every month, which strengthens the schema-mismatch reading
considerably — a one-month glitch would not repeat.

---

## D-009 — Congestion relief zone boundary definition

**Decided:** 38 Manhattan taxi zones classified as inside the CRZ, identified by
zone name as lying wholly or mostly below 60th Street. A trip is "treated" if
either pickup or dropoff falls in one of them.

**Why either end:** the surcharge applies to trips touching the zone, not only
those beginning there.

**Excluded as special cases:**
- Governor's/Ellis/Liberty Island (103, 104, 105) — ferry access only
- Roosevelt Island (202) — East River, not in the CRZ despite Manhattan borough

**Borderline calls, stated for challenge:**
- 229 Sutton Place/Turtle Bay North — extends to roughly 59th, counted in
- 163 Midtown North — roughly 47th–59th, counted in
- 43 Central Park — begins at 59th, counted out, since the bulk lies above
- 48/50 Clinton East/West — Hell's Kitchen runs to 59th, counted in

**Limitation:** TLC zone polygons do not align with 60th Street. Any
name-based classification misassigns some trips near the boundary. A
geospatial join against the CRZ shapefile would be more precise and is
recorded as future work.

---

## D-010 — Unequal comparison windows

**Found:** the pre-period (1 Nov – 4 Jan) is 65 days; the post-period
(5 Jan – 28 Feb) is 55 days. Comparing raw trip totals showed both groups
falling ~13%, which was entirely an artefact of the shorter window.

**Decision:** all period comparisons use daily rates, never totals.

Normalised, both groups **rose**: control +3.4% (32,920 → 34,041 trips/day),
treated +2.7% (85,164 → 87,442 trips/day).

---

## D-011 — Primary outcome: treated/control ratio

**Decided:** the daily ratio of treated to control trips is the outcome series,
rather than raw counts.

**Why:** city-wide shocks — weather, holidays, tourism, fare changes — move both
groups together and cancel in the ratio. A shift in the ratio is what a
policy effect would look like.

---

## D-012 — Result: no detectable effect on trip volume

| Period | Days | Mean ratio | SD |
|---|---|---|---|
| Pre  | 65 | 2.5849 | 0.2723 |
| Post | 55 | 2.5660 | 0.3221 |

The ratio moved **0.019**. The pre-period standard deviation is **0.2723** —
roughly 14× the observed shift. Daily counts swing 50–70% across the window
(e.g. treated trips ranged 53,026 on 6 Jan to 91,615 on 11 Jan).

**Conclusion:** no detectable change in the share of taxi trips touching the
CRZ following 5 January 2025. The shift is far inside ordinary day-to-day
variation.

**Not concluded:** that the policy had no effect. Trip volume is one outcome.
Duration, spatial distribution, time-of-day patterns and fare composition are
tested separately.

**Scope limitation:** a two-month post-period captures immediate behavioural
response but not durable substitution — a rider trying taxis in January may
switch to a transit pass by March. A like-for-like annual comparison
(full 2024 vs full 2025) would address this, at the cost of admitting more
confounders.

---

## D-013 — CBD surcharge appears on 4 January

Surcharge revenue is $0 on 1–3 January, $271.50 on 4 January, then $36,608 on
5 January.

**Investigated:** 401 trips on 4 January carry a surcharge. All were picked up
between 21:58 and 23:59, and 397 of 401 were dropped off after midnight.

**Conclusion:** not a data error. The surcharge is applied on **dropoff** time,
not pickup. Trips beginning before the policy start and ending after it are
charged correctly. The remaining 4 are within seconds of midnight.

**Implication for analysis:** any model keyed on pickup date will slightly
misattribute cross-midnight trips at the policy boundary. Affects 401 trips
out of 14.4M — immaterial, but recorded.

---

## D-014 — Result: congestion pricing increased trip speed

### The question

D-012 found no change in trip **volume**. That tests one mechanism: did the
$0.75 surcharge deter riders? It did not.

But the policy's stated aim was reducing congestion, not reducing taxi trips.
If it worked, the observable effect is that trips inside the zone got
**faster** — fewer cars on the same streets.

This section tests that.

### Step 1 — Duration, whole period

Daily average trip duration, averaged across each period.

| Period | Treated | Control | Treated SD | Control SD |
|---|---|---|---|---|
| Pre (65 days) | 18.65 min | 16.18 min | 1.70 | 1.37 |
| Post (55 days) | 15.26 min | 14.89 min | 0.90 | 0.84 |

- Treated fell **3.39 min** (−18.2%)
- Control fell **1.29 min** (−8.0%)
- **Difference-in-differences: −2.10 minutes**

**Why this is different from the volume result:** in D-012 the observed shift
(0.019) was 14× *smaller* than the standard deviation (0.27). Here the DiD
(−2.10 min) is *larger* than either group's standard deviation (1.70, 1.37).
The signal exceeds the noise rather than drowning in it.

**Second signal:** standard deviations roughly halved after the policy — 1.70 →
0.90 for treated, 1.37 → 0.84 for control. Trips became not only faster but
more **predictable**. Reduced congestion should compress the tail of slow
trips, which is exactly what this shows.

### Step 2 — The holiday confound

The pre-period contains Thanksgiving, Christmas and New Year. The post-period
contains no major holidays. Holiday traffic inflates Midtown congestion far
more than the outer boroughs, so some of the improvement could simply be the
holidays ending.

Monthly breakdown, treated-minus-control gap in the final column:

| Month | Treated | Control | Gap |
|---|---|---|---|
| Nov 2024 | 18.25 min | 16.31 min | **1.93** |
| Dec 2024 | 19.38 min | 16.19 min | **3.19** |
| Jan 2025 | 15.14 min | 14.76 min | **0.38** |
| Feb 2025 | 15.52 min | 15.08 min | **0.44** |

**The clean comparison is November versus February** — both ordinary
non-holiday months, neither distorted by seasonal traffic.

The gap fell from **1.93 to 0.44 minutes**, a **77% reduction** in the zone's
speed penalty.

**February is the decisive observation.** If this were the holidays ending, the
gap would have rebounded toward November's level once traffic normalised. It
did not — it stayed at 0.44.

December's 3.19 also supports the mechanism rather than undermining it: the
holiday spike is visible, and it hits the treated zone disproportionately,
which is what you would expect if Midtown congestion is the binding constraint.

### Step 3 — The distance confound

Duration alone is not conclusive. If trips simply got shorter, they would take
less time for reasons unrelated to traffic.

Mean trip distance, filtered to 0–100 miles:

| Month | Treated | Control |
|---|---|---|
| Nov 2024 | 3.08 mi | 3.81 mi |
| Dec 2024 | 3.08 mi | 3.74 mi |
| Jan 2025 | 2.87 mi | 3.66 mi |
| Feb 2025 | 2.83 mi | 3.60 mi |

Nov → Feb: treated **−8.1%**, control **−5.5%**.

Distance did fall in both groups, and slightly more in the treated group. So it
explains part of the duration drop — but not all of it. Treated duration fell
15% against an 8.1% distance drop; control fell 7.5% against 5.5%. The speed
gain outpaces the distance loss in both groups, and by more in treated.

To remove the confound entirely, switch to speed.

### Step 4 — Speed, which controls for distance

Computed as `trip_distance / trip_duration_min × 60`, filtered to 0.1–100 miles
and 1–180 minutes to exclude the impossible values documented in D-005.

| Month | Treated | Control | Gap |
|---|---|---|---|
| Nov 2024 | 9.78 mph | 12.44 mph | 2.66 |
| Dec 2024 | 9.34 mph | 12.28 mph | 2.94 |
| Jan 2025 | 10.79 mph | 13.01 mph | 2.22 |
| Feb 2025 | 10.48 mph | 12.86 mph | 2.38 |

**November → February:**

- Treated: 9.78 → 10.48 mph, **+7.2%**
- Control: 12.44 → 12.86 mph, **+3.4%**
- **Difference-in-differences: +3.8 percentage points**

Taxis inside the congestion zone sped up roughly **twice as much** as taxis
outside it. The speed gap between zones narrowed from 2.66 to 2.38 mph.

Because speed is distance per unit time, this result is unaffected by the
shortening of trips. The traffic effect is real and independent.

### Conclusion

Congestion pricing did not change how **many** taxi trips happened. It changed
how **fast** they moved.

Trips touching the congestion relief zone gained speed at roughly double the
citywide rate, and the effect persists in February, after holiday traffic had
normalised. It survives controlling for trip distance.

This is consistent with the policy's design intent: the $9 passenger-car toll
removes private vehicles from the zone, and the taxis that remain move through
less traffic. The $0.75 taxi surcharge is too small to deter riders — which is
why volume is flat — but the reduction in competing traffic is large enough to
show up clearly in trip times.

### What this analysis does not establish

**These are descriptive statistics, not inferential.** Comparing an effect size
to a standard deviation is a sanity check, not a hypothesis test. Before this
result could be published or relied upon:

1. **Formal significance testing** — a regression with an interaction term
   (treated × post), or paired t-tests on the daily series, producing an actual
   p-value and confidence interval.

2. **Day-of-week controls** — weekday and weekend traffic differ substantially,
   and the pre/post windows do not contain identical weekday mixes.

3. **Parallel-trends check** — the core DiD assumption is that treated and
   control would have moved together absent the policy. This must be verified
   on the pre-period, ideally with an event-study plot showing week-by-week
   coefficients before and after the intervention.

4. **Hourly breakdown** — the passenger-car toll varies by time of day, so peak
   effects may be substantially larger than the all-day average, and overnight
   effects near zero.

5. **Longer post-period** — two months captures the immediate traffic response.
   Whether the speed gain persists as drivers adapt is a separate question
   requiring 2025 data through at least mid-year.

### Comparison to published work

TLC testified to City Council in February 2025 that yellow taxi trips rose
approximately 10% in January 2025 versus January 2024, attributing it partly to
faster trips allowing more rides per shift.

A peer-reviewed DiD study on TLC data found ride-hailing trips **fell** 5.95%
post-policy.

This analysis uses a different baseline (Nov–Dec 2024 rather than year-over-
year) and a different vehicle class (yellow taxi rather than FHV), so the
results are not directly comparable. The volume finding here is neutral rather
than positive, which may reflect the different baseline period. The speed
finding is consistent with TLC's stated mechanism.