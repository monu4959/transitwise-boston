{{ config(
    materialized='incremental',
    unique_key='outage_id',
    incremental_strategy='merge',
    on_schema_change='fail'
) }}

-- One row per elevator outage: a run of consecutive snapshots in which MBTA reported the
-- elevator closed. The outage ends at the first snapshot that no longer lists it.
--
-- Incremental runs reprocess only snapshots that can still change a row:
--   * elevators whose outage was still open last run: from that outage's first snapshot,
--     so the row is extended or closed;
--   * every other elevator: only snapshots newer than the last run. (Reprocessing them
--     from an earlier point would cut a finished outage short and create a wrong row.)

with snapshots as (
    select * from {{ ref('int_alert_snapshots') }}
),

closures as (
    select c.*
    from {{ ref('int_elevator_closures') }} as c
    {% if is_incremental() %}
    left join (
        select facility_id, min(first_seen_at) as open_since
        from {{ this }}
        where is_ongoing
        group by facility_id
    ) as open_outages
      on open_outages.facility_id = c.facility_id
    where c.snapshot_at >= open_outages.open_since
       or c.snapshot_at > (select coalesce(max(last_checked_at), '1900-01-01'::timestamp_ntz)
                           from {{ this }})
    {% endif %}
),

-- Consecutive snapshot numbers minus a per-elevator row number is constant within a run
-- of consecutive snapshots ("gaps and islands"), so it identifies each outage.
islands as (
    select
        *,
        snapshot_seq - row_number() over (partition by facility_id order by snapshot_seq) as island
    from closures
),

outages as (
    select
        facility_id,
        min(snapshot_seq)                     as first_seq,
        max(snapshot_seq)                     as last_seq,
        min(snapshot_at)                      as first_seen_at,
        max(snapshot_at)                      as last_seen_at,
        count(*)                              as snapshots_seen,
        max_by(station_id, snapshot_at)       as station_id,
        array_union_agg(alert_ids)            as alert_ids,
        min(announced_start_at)               as announced_start_at,
        max_by(announced_end_at, snapshot_at) as announced_end_at,
        max_by(header, snapshot_at)           as header
    from islands
    group by facility_id, island
)

select
    o.facility_id || '@' || to_char(o.first_seen_at, 'YYYY-MM-DD"T"HH24:MI:SS.FF6') as outage_id,
    o.facility_id,
    o.station_id,
    o.first_seen_at,
    o.last_seen_at,
    cleared.snapshot_at                          as cleared_seen_at,
    cleared.snapshot_at is null                  as is_ongoing,
    before.snapshot_at is null                   as began_before_tracking,
    o.snapshots_seen,
    -- Snapshots are hours apart, so the true duration is only known within bounds:
    -- at least first-to-last sighting, at most last-working-to-first-cleared sighting.
    round(datediff('second', o.first_seen_at, o.last_seen_at) / 3600, 2)        as min_duration_hours,
    round(datediff('second', coalesce(before.snapshot_at, o.first_seen_at),
                   coalesce(cleared.snapshot_at, o.last_seen_at)) / 3600, 2)    as max_duration_hours,
    o.announced_start_at,
    o.announced_end_at,
    o.alert_ids,
    o.header,
    (select max(snapshot_at) from snapshots)     as last_checked_at
from outages as o
left join snapshots as cleared
  on cleared.snapshot_seq = o.last_seq + 1
left join snapshots as before
  on before.snapshot_seq = o.first_seq - 1
