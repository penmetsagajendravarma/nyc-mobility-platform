-- One row per trip, typed and with derived time fields.
-- No filtering beyond what ingestion already dropped: judgement calls about
-- fares and distances live in the intermediate layer, so this stays a faithful
-- typed view of raw.

with source as (

    select * from {{ source('tlc', 'yellow_trips') }}

),

typed as (

    select
        -- identifiers
        vendor_id::int                                  as vendor_id,
        pickup_location_id::int                         as pickup_location_id,
        dropoff_location_id::int                        as dropoff_location_id,
        payment_type::int                               as payment_type,
        ratecode_id::int                                as ratecode_id,

        -- timestamps
        pickup_datetime::timestamp                      as pickup_at,
        dropoff_datetime::timestamp                     as dropoff_at,

        -- derived time fields, used by nearly every downstream model
        extract(epoch from (dropoff_datetime - pickup_datetime)) / 60.0
                                                        as trip_duration_min,
        date_trunc('day',  pickup_datetime)::date        as pickup_date,
        extract(hour from pickup_datetime)::int          as pickup_hour,
        extract(dow  from pickup_datetime)::int          as pickup_dow,
        extract(dow  from pickup_datetime) in (0, 6)     as is_weekend,

        -- trip attributes
        passenger_count::int                            as passenger_count,
        trip_distance::numeric                          as trip_distance_mi,
        store_and_fwd_flag                              as store_and_fwd_flag,

        -- money
        fare_amount::numeric                            as fare_amount,
        extra::numeric                                  as extra,
        mta_tax::numeric                                as mta_tax,
        tip_amount::numeric                             as tip_amount,
        tolls_amount::numeric                           as tolls_amount,
        improvement_surcharge::numeric                  as improvement_surcharge,
        congestion_surcharge::numeric                   as congestion_surcharge,
        airport_fee::numeric                            as airport_fee,
        cbd_congestion_fee::numeric                     as cbd_congestion_fee,
        total_amount::numeric                           as total_amount,

        -- flags
        has_payment_detail                              as has_payment_detail,

        -- congestion pricing began 2025-01-05. Defining the period here means
        -- every downstream model uses the same boundary.
        pickup_datetime >= '2025-01-05'::timestamp      as is_post_congestion

    from source

)

select * from typed