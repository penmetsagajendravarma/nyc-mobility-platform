-- One row per day, with treated and control volumes side by side.
-- The ratio column is the key series for the difference-in-differences:
-- city-wide shocks (weather, holidays, tourism) move both groups together
-- and cancel out, so a shift in the ratio is what a policy effect looks like.

with enriched as (

    select * from {{ ref('int_trips_enriched') }}

)

select
    pickup_date,
    pickup_dow,
    is_weekend,
    is_post_congestion,

    count(*) filter (where touches_crz)                as treated_trips,
    count(*) filter (where not touches_crz)            as control_trips,
    count(*)                                           as total_trips,

    -- The outcome series. Robust to anything affecting the whole city.
    round(
        count(*) filter (where touches_crz)::numeric
        / nullif(count(*) filter (where not touches_crz), 0)
    , 4)                                               as treated_control_ratio,

    -- Revenue, restricted to rows with usable payment fields (D-005).
    round(sum(total_amount) filter (
        where touches_crz and has_payment_detail), 2)  as treated_revenue,
    round(sum(total_amount) filter (
        where not touches_crz and has_payment_detail), 2) as control_revenue,

    -- Congestion surcharge actually collected. Zero before 2025-01-05.
    round(sum(cbd_congestion_fee) filter (
        where has_payment_detail), 2)                  as cbd_fees_collected,

    -- Duration: a proxy for traffic speed. If the policy eased congestion,
    -- trips inside the zone should get faster.
    round(avg(trip_duration_min) filter (where touches_crz), 2)
                                                       as treated_avg_duration_min,
    round(avg(trip_duration_min) filter (where not touches_crz), 2)
                                                       as control_avg_duration_min

from enriched
group by 1, 2, 3, 4
order by 1