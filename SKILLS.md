# Repeatable tasks

## Add a stream feature
1. Add it to `config/features.yml` with an aggregation from `dfp.features.spec.AGGS` and a window in minutes.
2. If the window is longer than `tiles.retention_minutes` in `config/platform.yml`, raise retention (longest window + 60).
3. `pytest -q tests/test_tiles.py tests/test_api.py`, then a dev run: the platform must stay exact.

## Add a provider and its rule
1. `config/compliance.yml`: `max_age_hours`, and if needed `stale_if_error_hours` or `not_before_daily_hour`.
2. `config/features.yml`: the feature that reads it. In the lab, add its world behaviour to `config/world.yml` and
   the name to `PROVIDERS` in `dfp/sim/world.py`.
3. Run the dev seeds; the gate fails on any rule break.

## Add a design or an ablation
1. Add it under `designs` in `config/platform.yml`; ablations set `base: platform` and override one switch.
2. If it needs new behaviour, add a switch in `dfp/sim/designs.py` that calls production code, not a copy of it.
3. Dev run, gate, report. Do not touch the held-out seeds.

## Run the development seeds and refresh the reports
`python -m dfp.cli run dev && python -m dfp.cli gate dev && python -m dfp.cli report`, then commit `reports/dev.json`,
REPORT.md, README.md and `docs/figures`.

## Run the held-out seeds (once)
Only after the gates are final. `python -m dfp.cli run heldout && python -m dfp.cli gate heldout && python -m dfp.cli report`,
commit `reports/heldout.lock` with `reports/heldout.json` in one commit, and never rerun.

## Refresh the dashboard screenshots
`cd web && npm run build`, then `python scripts/screenshots.py` (Playwright with the system Chrome).

## Deploy
`sam build -t infra/template.yaml && sam deploy --guided`. Then create the registry tables (`dfp.registry.db.migrate`),
add tenants with `add_tenant`, and register the features from `config/features.yml`.
