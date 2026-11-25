-- Returns a row for every broken outage, so the test fails if anything comes back:
-- an outage that ends before it starts, two outages of one elevator that overlap, or an
-- elevator with more than one ongoing outage.
with outages as (
    select * from {{ ref('fct_elevator_outages') }}
),

ordered as (
    select
        *,
        lead(first_seen_at) over (partition by facility_id order by first_seen_at) as next_first_seen_at,
        count_if(is_ongoing) over (partition by facility_id)                       as ongoing_count
    from outages
)

select outage_id, 'ends before it starts' as problem
from ordered where last_seen_at < first_seen_at
union all
select outage_id, 'overlaps the next outage of the same elevator'
from ordered where next_first_seen_at <= coalesce(cleared_seen_at, last_seen_at)
union all
select outage_id, 'elevator has more than one ongoing outage'
from ordered where is_ongoing and ongoing_count > 1
