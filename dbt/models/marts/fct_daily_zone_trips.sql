-- One row per date per pickup zone. The grain for any geographic or
-- zone-level view: maps, per-neighbourhood trends, supply-demand mismatch.
--
-- Aggregated on PICKUP zone only. A trip has two ends, so summing trips
-- across all rows here double-counts nothing, but it also means dropoff
-- demand is not represented. Documented rather than silently assumed.

with enriched as (

    select * from {{ ref('int_trips_enriched') }}

)

select
    pickup_date,
    pickup_location_id,
    pickup_zone,
    pickup_borough,
    pickup_in_crz,
    is_post_congestion,
    is_weekend,

    count(*)                                            as trips,

    round(avg(trip_duration_min), 2)                    as avg_duration_min,
    round(avg(trip_distance_mi), 3)                     as avg_distance_mi,

    -- Speed, on the same filters used throughout the analysis (D-014).
    round(avg(
        trip_distance_mi / nullif(trip_duration_min, 0) * 60
    ) filter (
        where trip_distance_mi between 0.1 and 100
          and trip_duration_min between 1 and 180
    ), 2)                                               as avg_speed_mph,

    -- Money, restricted to rows with usable payment fields (D-005).
    count(*) filter (where has_payment_detail)          as trips_with_payment,
    round(sum(total_amount) filter (
        where has_payment_detail), 2)                   as revenue,
    round(avg(total_amount) filter (
        where has_payment_detail), 2)                   as avg_fare,

    -- Card trips only: cash tips are not recorded by the meter, so
    -- including them averages real tips against structural zeros.
    round(avg(tip_amount) filter (
        where has_payment_detail and payment_type = 1), 2) as avg_tip_card,

    round(sum(cbd_congestion_fee) filter (
        where has_payment_detail), 2)                   as cbd_fees

from enriched
where pickup_location_id is not null
group by 1, 2, 3, 4, 5, 6, 7
order by 1, 2