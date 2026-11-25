-- Per station: how often its elevators were reported out while the pipeline was
-- watching, and how many planned trips had to route around it.
with outages as (
    select
        station_id,
        count(*)                          as outages_recorded,
        count_if(is_ongoing)              as elevators_out_now,
        round(sum(min_duration_hours), 1) as outage_hours_at_least,
        round(sum(max_duration_hours), 1) as outage_hours_at_most,
        max(last_seen_at)                 as last_outage_seen_at
    from {{ ref('fct_elevator_outages') }}
    group by station_id
),

trips as (
    select station_id, count(distinct trip_id) as trips_routed_around
    from {{ ref('fct_trip_blockers') }}
    where station_id is not null
    group by station_id
)

select
    s.station_id,
    s.station_name,
    s.elevator_count,
    coalesce(o.outages_recorded, 0)      as outages_recorded,
    coalesce(o.elevators_out_now, 0)     as elevators_out_now,
    coalesce(o.outage_hours_at_least, 0) as outage_hours_at_least,
    coalesce(o.outage_hours_at_most, 0)  as outage_hours_at_most,
    o.last_outage_seen_at,
    coalesce(t.trips_routed_around, 0)   as trips_routed_around
from {{ ref('dim_stations') }} as s
left join outages as o on o.station_id = s.station_id
left join trips as t on t.station_id = s.station_id
where s.elevator_count > 0
   or o.station_id is not null
   or t.station_id is not null
