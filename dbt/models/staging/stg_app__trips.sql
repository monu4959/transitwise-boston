-- One row per trip the app planned. The log has no ID column, so the key is a hash of
-- when, where from, where to and which part of the app logged it.
select
    md5(concat_ws('|', logged_at::string, coalesce(source, ''),
                  coalesce(origin, ''), coalesce(destination, '')))   as trip_id,
    logged_at,
    source,
    case
        when source like 'eval%'    then 'evaluation'
        when source like 'monitor%' then 'monitoring'
        when source = 'mcp'         then 'agent'
        when source = 'notebook'    then 'notebook'
        else 'rider'                                    -- web and app*
    end                                                 as source_group,
    origin,
    destination,
    ok                                                  as is_ok,
    safe                                                as is_safe,
    rerouted                                            as is_rerouted,
    original_route,
    new_route,
    minutes                                             as trip_minutes,
    blocking_stations,
    reason
from {{ source('logs', 'agent_log') }}
