-- Trips joined to zone names and classified by congestion relief zone (CRZ).
--
-- The CRZ is Manhattan below 60th Street. TLC's data carries no such flag, so
-- the boundary is defined here by zone name. This list is the single most
-- consequential judgement call in the project: it defines the treatment group
-- for the difference-in-differences analysis. See docs/decisions.md D-009.

with crz_zones as (

    -- Manhattan zones lying wholly or mostly below 60th Street.
    select unnest(array[
        4,    -- Alphabet City
        12,   -- Battery Park
        13,   -- Battery Park City
        45,   -- Chinatown
        48,   -- Clinton East
        50,   -- Clinton West
        68,   -- East Chelsea
        79,   -- East Village
        87,   -- Financial District North
        88,   -- Financial District South
        90,   -- Flatiron
        100,  -- Garment District
        107,  -- Gramercy
        113,  -- Greenwich Village North
        114,  -- Greenwich Village South
        125,  -- Hudson Sq
        137,  -- Kips Bay
        144,  -- Little Italy/NoLiTa
        148,  -- Lower East Side
        158,  -- Meatpacking/West Village West
        161,  -- Midtown Center
        162,  -- Midtown East
        163,  -- Midtown North
        164,  -- Midtown South
        170,  -- Murray Hill
        186,  -- Penn Station/Madison Sq West
        209,  -- Seaport
        211,  -- SoHo
        224,  -- Stuy Town/Peter Cooper Village
        229,  -- Sutton Place/Turtle Bay North
        230,  -- Times Sq/Theatre District
        231,  -- TriBeCa/Civic Center
        232,  -- Two Bridges/Seward Park
        233,  -- UN/Turtle Bay South
        234,  -- Union Sq
        246,  -- West Chelsea/Hudson Yards
        249,  -- West Village
        261   -- World Trade Center
    ]) as location_id

),

trips as (

    select * from {{ ref('stg_yellow_trips') }}

),

zones as (

    select
        "LocationID"   as location_id,
        "Borough"      as borough,
        "Zone"         as zone_name,
        service_zone
    from {{ source('tlc_ref', 'taxi_zone_lookup') }}

)

select
    t.*,

    pu.borough      as pickup_borough,
    pu.zone_name    as pickup_zone,
    do_.borough     as dropoff_borough,
    do_.zone_name   as dropoff_zone,

    -- CRZ membership
    pu.location_id in (select location_id from crz_zones) as pickup_in_crz,
    do_.location_id in (select location_id from crz_zones) as dropoff_in_crz,

    -- A trip is "treated" if either end sits inside the zone, since the
    -- surcharge applies to trips touching the CRZ at all.
    (pu.location_id in (select location_id from crz_zones)
     or do_.location_id in (select location_id from crz_zones)) as touches_crz

from trips t
left join zones pu  on t.pickup_location_id  = pu.location_id
left join zones do_ on t.dropoff_location_id = do_.location_id