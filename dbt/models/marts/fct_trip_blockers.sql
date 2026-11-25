-- One row per station a planned trip had to avoid, matched to the elevator outages the
-- pipeline had recorded there at that time. The trip log stores station names, and some
-- entries are a blocked hop ("Government Center → Park Street"), so each side is matched.
with blockers as (
    select
        t.trip_id,
        t.logged_at,
        b.index           as blocker_no,
        b.value::string   as blocker
    from {{ ref('stg_app__trips') }} as t,
         lateral flatten(input => t.blocking_stations) as b
),

blocker_stations as (
    select
        bl.*,
        iff(contains(bl.blocker, '→'), 'hop', 'station') as blocker_kind,
        trim(p.value)                                    as station_name
    from blockers as bl,
         lateral split_to_table(bl.blocker, '→') as p
),

matched as (
    select
        b.trip_id,
        b.blocker_no,
        b.station_name,
        count(o.outage_id) as recorded_outages
    from blocker_stations as b
    join {{ ref('stg_mbta__stations') }} as s
      on s.station_name = b.station_name
    join {{ ref('fct_elevator_outages') }} as o
      on o.station_id = s.station_id
     and coalesce(o.announced_start_at, o.first_seen_at) <= b.logged_at
     and (o.cleared_seen_at is null or b.logged_at < o.cleared_seen_at)
    group by all
)

select
    b.trip_id || '#' || b.blocker_no || ':' || b.station_name as trip_blocker_id,
    b.trip_id,
    b.logged_at,
    b.blocker,
    b.blocker_kind,
    b.station_name,
    s.station_id,
    coalesce(m.recorded_outages, 0)                         as recorded_outages
from blocker_stations as b
left join {{ ref('stg_mbta__stations') }} as s
  on s.station_name = b.station_name
left join matched as m
  on m.trip_id = b.trip_id
 and m.blocker_no = b.blocker_no
 and m.station_name = b.station_name
