# SOURCE_MAPPING.md

Maps provider-specific fields into canonical fields.

## 1. Finnhub
### Basic financials / metrics
- provider: Finnhub `/stock/metric`
- canonical source: `finnhub`
- source_type: `fundamentals`
- event_type: `basic_financials`
- symbol: provider symbol
- event_time: ingestion time if provider does not expose a direct event time
- payload keys: normalized subset only

### Insider transactions
- provider: Finnhub insider transactions endpoint
- source_type: `fundamentals`
- event_type: `insider_transaction`
- map provider fields into:
  - insider_name
  - insider_role
  - transaction_type
  - shares
  - price
  - transaction_value
  - filing_date

### Earnings calendar
- source_type: `fundamentals`
- event_type: `earnings_calendar`
- map estimated EPS/revenue and fiscal metadata

## 2. FRED
- source: `fred`
- source_type: `macro`
- event_type: `macro_release`
- symbol: null
- payload fields:
  - series_id
  - value
  - release_name
  - period
  - units

## 3. SEC
- source: `sec`
- source_type: `filing`
- event_type: `filing`
- symbol: derived from company/ticker mapping if available
- payload fields:
  - form_type
  - accession_no
  - filed_at
  - title
  - primary_doc_url
  - sentiment

## 4. Broker
### Bars / quotes
- source: `broker`
- source_type: `price`
- event_type: `bar_1m` or `quote`
- symbol: ticker
- payload fields:
  - timeframe
  - OHLCV fields for bars
  - bid/ask/last fields for quotes

### Orders / positions
- source_type: `order` or `position`
- event_type: `order_update` or `position_snapshot`

## 5. Mapping rules
- Normalize timestamps to UTC ISO8601.
- Preserve source identifiers in payload if needed.
- Add quality flags instead of silently dropping malformed fields.
