-- One row per planned trip, with how many stations it had to route around.
select
    trip_id,
    logged_at,
    logged_at::date                            as logged_on,
    source,
    source_group,
    origin,
    destination,
    is_ok,
    is_safe,
    is_rerouted,
    trip_minutes,
    coalesce(array_size(blocking_stations), 0) as blocked_station_count,
    original_route,
    new_route,
    reason
from {{ ref('stg_app__trips') }}
