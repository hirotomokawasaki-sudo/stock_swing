# EXECUTION_POLICY.md

## 1. Execution authority
Execution authority belongs to the execution layer only.
Prompts, chat outputs, and strategy modules are not execution authority.

## 2. Initial scope
- Paper execution only in early phases
- Market and limit orders only
- Day orders only unless explicitly approved otherwise

## 3. Required checks before submission
- runtime mode check
- risk pass
- decision schema validation
- duplicate order suppression
- broker connectivity available
- symbol tradability confirmed

## 4. Reconciliation
Every order submission must be reconciled against broker truth.
Internal state must not invent fills or positions.
