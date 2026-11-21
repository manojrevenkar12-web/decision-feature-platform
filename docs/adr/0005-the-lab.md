# 5. How the designs are compared

## Decision
- One `simulate(seed)` draws everything random once: customers and the people behind them (12% bank with two
  lenders), transactions with bursts before some decisions, arrival delays (90% within seconds, 1% hours late),
  2.5% redeliveries, decisions with 15% double submits, provider records that change over time, every call's
  latency and error, outages, every tier read's latency, and Lambda container lifetimes.
- Each design replays the same `Observed` world. Deliveries and decisions are merged in time order; a provider
  response lands in the cache only when its call completes.
- `evaluate.py` grades each decision against the hidden truth: the value knowable at the gate, the provider record
  current at the decision, and the lenders' rules.
- Intervals resample whole days (a block bootstrap), because outages and bursts make decisions on the same day
  move together.
- Development seeds 1–3 tune the world and set the gates. The held-out seeds run once behind `reports/heldout.lock`.

## Consequences
The numbers say what happens under the world's assumptions, which are config. Changing an assumption means a new
dev run; the held-out result stays as it was.
