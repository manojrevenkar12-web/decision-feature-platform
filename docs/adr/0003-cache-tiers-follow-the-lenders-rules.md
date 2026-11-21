# 3. Cache tiers that follow the lenders' rules

## Context
Provider calls are the largest variable cost of a decision, and the slowest part. Reuse is limited by contract and
regulation, and the limits differ: a bureau report may be reused for 7 days, a sanctions screen must follow the
06:00 list publication, open-banking data for an hour, a device check never.

## Decision
- The rules are config (`config/compliance.yml`), read into `FreshnessPolicy`. Every read checks age, the
  publication rule, and whether the response is from the future.
- Tiers, fastest first: in-process LRU (at most 5 minutes, per container), Redis (bounded memory, evicts), and
  DynamoDB (TTL = maximum age plus the stale-if-error grace). A fresh hit is promoted to the faster tiers.
- Keys always include the tenant. One lender's paid report is never served to another, even for the same person.

## Consequences
- In the lab, the tiered cache cut provider spend by about 83% against querying every time. A single Redis tier
  with the same rules cut it by about 63%, because Redis evictions forced repeat purchases.
- One 24-hour TTL for every provider saves less than the per-provider rules and breaks them tens of thousands of times.
- The in-process tier served only about 1% of features, because decisions spread over many containers. It is kept
  small and short-lived; its value is under bursts.
