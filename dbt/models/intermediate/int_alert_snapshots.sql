-- Every snapshot the pipeline has taken, numbered in order. Outages are measured in
-- snapshots, not clock time: an elevator is "still out" if it was closed in one snapshot
-- and in the next one, however far apart they were, so a skipped run can't split an outage.
select
    snapshot_at,
    row_number() over (order by snapshot_at) as snapshot_seq
from (select distinct snapshot_at from {{ ref('stg_mbta__alerts') }})
