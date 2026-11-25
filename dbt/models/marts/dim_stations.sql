select
    s.station_id,
    s.station_name,
    s.municipality,
    s.latitude,
    s.longitude,
    s.wheelchair_boarding,
    s.wheelchair_status,
    count(f.facility_id) as elevator_count
from {{ ref('stg_mbta__stations') }} as s
left join {{ ref('stg_mbta__facilities') }} as f
  on f.station_id = s.station_id
 and f.facility_type = 'ELEVATOR'
group by all
