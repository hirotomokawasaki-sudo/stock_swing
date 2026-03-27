# CANONICAL_SCHEMA.md

Defines the canonical internal schema used after normalization.
This schema is the contract between raw ingestion and downstream feature/strategy layers.

## 1. Canonical event record
```json
{
  "record_id": "uuid-or-hash",
  "schema_version": "v1",
  "source": "finnhub|fred|sec|broker",
  "source_type": "fundamentals|macro|filing|price|order|position",
  "symbol": "AAPL",
  "event_type": "earnings_calendar|insider_transaction|macro_release|filing|bar_1m|quote|order_update",
  "event_time": "2026-03-06T13:30:00Z",
  "as_of": "2026-03-06",
  "ingested_at": "2026-03-06T13:31:00Z",
  "timezone": "UTC",
  "payload_version": "provider-specific-version-or-null",
  "quality_flags": [],
  "payload": {}
}
```

## 2. Required fields
- `record_id`: unique identifier for the normalized record
- `schema_version`: canonical schema version
- `source`: source family
- `source_type`: semantic category of source data
- `symbol`: ticker if applicable, else null for macro-only records
- `event_type`: normalized event type
- `event_time`: event timestamp in ISO8601 UTC
- `as_of`: business date used for partitioning
- `ingested_at`: ingestion timestamp in ISO8601 UTC
- `timezone`: source timezone or normalized timezone
- `payload_version`: optional provider schema/version indicator
- `quality_flags`: array of warnings or integrity notes
- `payload`: normalized event-specific content

## 3. Canonical payload examples
### Earnings calendar payload
```json
{
  "estimate_eps": 2.15,
  "estimate_revenue": 89400000000,
  "fiscal_period": "Q2 2026",
  "confirmed": true
}
```

### Insider transaction payload
```json
{
  "insider_name": "Jane Doe",
  "insider_role": "Director",
  "transaction_type": "P",
  "shares": 2500,
  "price": 187.4,
  "transaction_value": 468500,
  "filing_date": "2026-03-04"
}
```

### Macro payload
```json
{
  "series_id": "CPIAUCSL",
  "value": 319.082,
  "release_name": "Consumer Price Index",
  "period": "2026-02",
  "units": "Index 1982-1984=100"
}
```

### Filing payload
```json
{
  "form_type": "8-K",
  "accession_no": "0000320193-26-000012",
  "filed_at": "2026-03-05T21:32:00Z",
  "title": "Current report",
  "primary_doc_url": "https://...",
  "sentiment": null
}
```

### Price bar payload
```json
{
  "timeframe": "1m",
  "open": 183.12,
  "high": 183.45,
  "low": 182.91,
  "close": 183.31,
  "volume": 1912200
}
```

## 4. Design rules
- Raw provider payloads stay in `data/raw/`.
- Canonical records are provider-neutral and downstream-safe.
- Downstream modules should not need provider-specific knowledge for common fields.
- Unknown or partial values must use explicit flags, not hidden null assumptions.

## 5. Partitioning recommendation
Canonical files or tables should be partitioned by:
- `as_of`
- `source`
- optional `symbol`
- optional `event_type`

## 6. Versioning
Start with `v1`.
Any backward-incompatible change requires a version bump and migration note.
