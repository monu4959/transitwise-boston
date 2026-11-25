-- One row per alert per snapshot, renamed and typed. All times are UTC: LOADED_AT is
-- written in UTC, and MBTA's ISO timestamps carry their own offset.
select
    id                                                                        as alert_id,
    effect,
    cause,
    severity,
    lifecycle,
    header,
    description,
    nullif(facility_ids, '')                                                  as facility_ids,
    nullif(station_ids, '')                                                   as station_ids,
    nullif(route_ids, '')                                                     as route_ids,
    convert_timezone('UTC', try_to_timestamp_tz(active_start))::timestamp_ntz as announced_start_at,
    convert_timezone('UTC', try_to_timestamp_tz(active_end))::timestamp_ntz   as announced_end_at,
    convert_timezone('UTC', try_to_timestamp_tz(updated_at))::timestamp_ntz   as mbta_updated_at,
    loaded_at                                                                 as snapshot_at
from {{ source('raw', 'alerts_history') }}
{% if var('snapshots_until') %}
where loaded_at <= '{{ var("snapshots_until") }}'::timestamp_ntz
{% endif %}
