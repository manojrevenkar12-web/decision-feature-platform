# Working on this repository

## Fast feedback

- `pytest -q` runs in about 5 s: small worlds, moto for DynamoDB, fakeredis, SQLite for the registry.
- `ruff check . && ruff format --check . && mypy src` for lint and types. `cfn-lint infra/template.yaml` for the template.
- `python -m dfp.cli run dev && python -m dfp.cli gate dev && python -m dfp.cli report` runs the three development
  seeds (about 3.5 minutes on 3 cores) and regenerates REPORT.md, the figures and the README block.
- `cd web && npm test && npm run typecheck && npm run lint` for the dashboard.

## Invariants

Each has a test or a CI step.

- **The truth stays in the world.** Designs get `Observed`: what the stream delivers (duplicates unmarked), the
  decisions, the providers' answers, and how AWS behaved. Which deliveries were duplicates, when events really
  arrived, and what each provider record said at each moment stay in `World` and are read only by
  `dfp/sim/evaluate.py` (`tests/test_boundaries.py`).
- **The world does not read the platform's settings.** `world.py` loads `world.yml` only; the platform and the
  designs never import `World` or `simulate` (`tests/test_boundaries.py`).
- **Same luck for every design.** Every random draw happens once per seed in `simulate`: each provider call's
  latency and error, each tier read, each container's lifetime. Designs replay the same draws
  (`tests/test_designs.py::test_every_design_is_graded_on_the_same_decisions`).
- **An event counts once.** The consumer claims the event id in the same DynamoDB transaction that updates the
  buckets (`tests/test_consumer.py`).
- **A feature is what was known at the gate.** Windows are minute-aligned in event time and count only events
  that had arrived by the decision. Backfills use `pit.as_of`, never `pit.leaky` (`tests/test_offline.py`, `tests/test_tiles.py`).
- **A report goes only to the lender who paid for it, and only within its rule.** Cache keys carry the tenant;
  `FreshnessPolicy` decides what may be served (`tests/test_cache.py`, `tests/test_api.py`).
- **The tenant comes from the key**, never from the request body (`tests/test_api.py`, `tests/test_registry.py`).
- **Settings live in `config/`**: the world in `world.yml`; the lenders' rules in `compliance.yml`; features in
  `features.yml`; the designs in `platform.yml`; thresholds in `gates.yml`; seeds in `seeds.yml`.
- **Reports are generated, never edited.** CI regenerates REPORT.md and the README block and fails on a diff.

## Held-out seeds

- `config/seeds.yml` lists them. `python -m dfp.cli run heldout` writes `reports/heldout.lock` before it runs and
  refuses to run again. CI checks the lock was committed once.
- Gates were set from the development seeds before the held-out run. Never loosen a gate after it.
- If a change needs new held-out evidence, add new seeds under a new name and record why in an ADR.

## Data

Everything is simulated: lenders, customers, transactions, providers and AWS behaviour. No real personal data.
