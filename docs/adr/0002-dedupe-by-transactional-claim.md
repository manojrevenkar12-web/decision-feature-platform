# 2. Dedupe by a claim in the same transaction as the update

## Context
Lambda on Kinesis retries a batch from the first failed record, and bisect-on-error retries halves of a batch.
Either way, records already applied arrive again. Bucket updates are additive (`ADD n :one`), so a redelivered
record counts twice.

## Decision
`DynamoBucketStore.apply` is one `TransactWriteItems`: a conditional `Put` of the event id into the idempotency
table (fails if a live claim exists) and the `Update` of the minute bucket and the hour tile. A failed condition
means a duplicate and changes nothing. The claim expires after 48 hours (DynamoDB TTL), longer than any retry.

## Alternatives
- Claim first, then update: a crash between them loses the event.
- Store the set of event ids in each bucket: unbounded item size on busy customers.
- Exactly-once via Flink or Kinesis Data Analytics: a second runtime to operate for one guarantee.

## Consequences
Each event costs one transaction (three writes). Without dedupe, the lab's platform got 16% of decisions' stream
features wrong at a 2.5% redelivery rate. The 24-hour sum is the most exposed feature because its window holds
the most events.
