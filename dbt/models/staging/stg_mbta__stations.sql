select
    station_id,
    name                as station_name,
    municipality,
    latitude,
    longitude,
    wheelchair_boarding,
    wheelchair_status,
    loaded_at           as refreshed_at
from {{ source('raw', 'stations') }}
