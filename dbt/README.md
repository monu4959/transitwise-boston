# TransitWise analytics (dbt)

Turns what the pipeline loads into Snowflake into tables you can analyze: elevator outage
periods, station reliability and trip facts. Runs on dbt v2 (2.0.11); also tested on dbt
Core 1.12 with the same results.

```
RAW / LOGS (loaded by Python)     STAGING (views)               MARTS (tables)
alerts_history  ───────────────>  stg_mbta__alerts ──> int_alert_snapshots
                                                   └─> int_elevator_closures ──> fct_elevator_outages (incremental)
stations, facilities ──────────>  stg_mbta__stations, stg_mbta__facilities ──> dim_stations, dim_elevators
agent_log ─────────────────────>  stg_app__trips ──> fct_trips, fct_trip_blockers ──> station_reliability
                                                     current_elevator_outages (view, replaces the CLEAN view)
```

## The main problem: snapshots into outage periods

`RAW.ALERTS_HISTORY` gets a full copy of every active MBTA alert on each pipeline run, so an
elevator that is out for a week appears in every snapshot that week. `fct_elevator_outages`
turns that into one row per outage: first and last snapshot that showed the elevator closed,
the first snapshot that no longer listed it, and whether it is still out.

- **Measured in snapshots, not clock time.** GitHub schedules the loader every 30 minutes but
  runs it only a few times a day (snapshots are usually 4 to 15 hours apart). An outage ends
  only when a snapshot actually shows the elevator working, so a skipped run can't split it.
- **Durations are bounds.** The true start and end fall between snapshots, so the table gives
  `min_duration_hours` (first to last sighting) and `max_duration_hours` (last snapshot
  working to first snapshot working again).
- **Incremental.** Each run merges only what can change: outages still open last run
  (reprocessed from their start, so they are extended or closed) and newer snapshots for
  every other elevator. Checked on real data: building in four incremental steps gave the
  same 54 rows as a full rebuild, with no differences.

## Tests

- Data tests on every model: unique and not-null keys, accepted values, relationships.
  Relationships to `dim_elevators`/`dim_stations` only warn: `RAW.FACILITIES` and
  `RAW.STATIONS` are refreshed by hand, so a new elevator can appear in alerts first. (This
  test found that Courthouse was missing: it is served only by the Silver Line, which MBTA
  files as a bus. `build_db.py` now loads the Silver Line Waterfront stations too.)
- `tests/assert_elevator_outages_are_consistent.sql`: no outage ends before it starts, no two
  outages of one elevator overlap, at most one ongoing outage per elevator.
- Unit tests (`models/marts/_unit_tests.yml`) on hand-made snapshots: an elevator that comes
  back, a 13-hour gap that must not split an outage, and an incremental run that must extend
  an open outage without cutting a finished one short.
- Source freshness on `alerts_history`: warn after 12 hours, fail after 24.

## Run it

Uses the app's Snowflake login from `.env` (`SNOWFLAKE_*`, key pair). `run_dbt.py` loads it
the way the app does and passes the key to dbt in memory.

```
py -3.12 -m venv ~/.venvs/transitwise-dbt      # once; kept outside OneDrive
~/.venvs/transitwise-dbt/Scripts/activate      # macOS/Linux: source ~/.venvs/transitwise-dbt/bin/activate
pip install -r dbt/requirements.txt

python dbt/run_dbt.py debug                                    # check the connection
python dbt/run_dbt.py build --exclude-resource-type unit_test  # models + data tests (DEV_ schemas)
python dbt/run_dbt.py test --select test_type:unit             # unit tests (need the models built once)
python dbt/run_dbt.py source freshness
python dbt/run_dbt.py docs generate                            # then: docs serve (lineage graph)
```

Local runs write to `DEV_STAGING` and `DEV_MARTS`. Production (`--target prod`) writes to
`STAGING` and `MARTS`, and only runs in GitHub Actions.

## In production

`.github/workflows/load_alerts.yml` runs dbt in the same job as the loader: freshness check
first (how stale the data was before this run; never blocks the load), then the load, then
`dbt build` while the warehouse is still awake. Snowflake bills at least a minute each time
the warehouse wakes, so running dbt in the same job costs seconds instead of an extra wake-up.
A full build takes about 15 seconds.

## dbt v2 and v1

The project was built on dbt Core 1.12 and moved to dbt v2 (the Rust engine) without
changing a model: on the same data, v1 and v2 produced identical rows in every mart table.
v2 is free to use internally, including in CI; `run_dbt.py` turns off its anonymous usage
stats. To run on v1 instead, install `dbt-core==1.12.7 dbt-snowflake==1.12.5`; nothing
else changes.
