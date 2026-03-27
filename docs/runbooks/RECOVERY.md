# RECOVERY.md

## Immediate safe response
1. Stop new order generation
2. Preserve audit state
3. Verify broker truth
4. Verify runtime mode
5. Verify latest decision outputs
6. Reconcile orders and positions

## Typical recovery categories
- source outage
- stale data
- broker outage
- config corruption
- duplicate decision generation
- audit integrity failure

## Rule
Do not recreate orders from memory or chat history.
Always rebuild state from broker truth plus persisted audit/decision records.
