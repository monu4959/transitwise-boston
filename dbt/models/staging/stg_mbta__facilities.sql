select
    facility_id,
    type                as facility_type,
    short_name,
    long_name,
    station_id,
    loaded_at           as refreshed_at
from {{ source('raw', 'facilities') }}
