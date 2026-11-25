select
    f.facility_id,
    f.short_name,
    f.long_name,
    f.station_id,
    s.station_name,
    f.refreshed_at
from {{ ref('stg_mbta__facilities') }} as f
left join {{ ref('stg_mbta__stations') }} as s
  on s.station_id = f.station_id
where f.facility_type = 'ELEVATOR'
