-- One row per elevator per snapshot in which MBTA reported it closed. An elevator can
-- have more than one closure alert at once; they are combined here.
with closures as (
    select
        trim(f.value)                                as facility_id,
        a.snapshot_at,
        a.alert_id,
        a.header,
        a.announced_start_at,
        a.announced_end_at,
        regexp_substr(a.station_ids, 'place-[^,]+') as station_id   -- parent station
    from {{ ref('stg_mbta__alerts') }} as a,
         lateral split_to_table(a.facility_ids, ',') as f
    where a.effect = 'ELEVATOR_CLOSURE'
)

select
    c.facility_id,
    c.snapshot_at,
    s.snapshot_seq,
    max(c.station_id)                                                  as station_id,
    array_agg(distinct c.alert_id) within group (order by c.alert_id) as alert_ids,
    min(c.announced_start_at)                                          as announced_start_at,
    iff(count_if(c.announced_end_at is null) > 0, null,
        max(c.announced_end_at))                                       as announced_end_at,
    max_by(c.header, c.alert_id)                                       as header
from closures as c
join {{ ref('int_alert_snapshots') }} as s
  on s.snapshot_at = c.snapshot_at
group by c.facility_id, c.snapshot_at, s.snapshot_seq
