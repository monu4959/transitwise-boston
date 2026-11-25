{{ config(materialized='view') }}

-- Elevators out of service in the latest snapshot, one row per affected station: the same
-- rows as the hand-written CLEAN.CURRENT_ELEVATOR_OUTAGES view (sql/02_clean_views.sql).
-- STATION_IDS also holds platform and entrance IDs; the join keeps only parent stations.
with latest as (
    select *
    from {{ ref('stg_mbta__alerts') }}
    where effect = 'ELEVATOR_CLOSURE'
      and snapshot_at = (select max(snapshot_at) from {{ ref('stg_mbta__alerts') }})
),

alert_stations as (
    select a.facility_ids, a.header, trim(st.value) as station_id
    from latest as a,
         lateral split_to_table(a.station_ids, ',') as st
)

select distinct
    s.station_id,
    s.station_name   as station,
    a.facility_ids   as elevator,
    a.header
from alert_stations as a
join {{ ref('stg_mbta__stations') }} as s
  on s.station_id = a.station_id
