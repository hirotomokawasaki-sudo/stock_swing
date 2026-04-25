# Parameter Tuning Guide

## ⚠️ WARNING
Parameter changes directly affect trading behavior. Always use validation before applying changes.

## Available Parameters

### 1. max_position_size
- **Current**: $400
- **Safe range**: $100 - $1000
- **Description**: Maximum position size per symbol
- **Risk level**: HIGH
- **Impact**: Larger values = more capital at risk per symbol

### 2. min_signal_strength
- **Current**: 0.50
- **Safe range**: 0.30 - 0.80
- **Description**: Minimum signal strength to act on
- **Risk level**: MEDIUM
- **Impact**: Higher = fewer signals but higher quality

### 3. min_confidence
- **Current**: 0.40
- **Safe range**: 0.30 - 0.80
- **Description**: Minimum confidence threshold
- **Risk level**: MEDIUM
- **Impact**: Higher = stricter filtering

### 4. symbol_position_limit_pct
- **Current**: 0.10 (10%)
- **Safe range**: 0.05 - 0.20
- **Description**: Maximum position per symbol (% of equity)
- **Risk level**: HIGH
- **Impact**: Higher = more concentration risk

## API Usage

### Get all parameters
```bash
curl http://localhost:3333/api/parameters
```

### Validate a value (DRY RUN)
```bash
curl "http://localhost:3333/api/parameters/max_position_size/validate?value=500"
```

## Implementation Status

### Phase 1: READ-ONLY ✅
- API to view current parameters
- Display safe ranges

### Phase 2: VALIDATION ✅
- Validate values without applying
- Show warnings and impact estimation
- Test boundary conditions

### Phase 3: WRITE (NOT YET IMPLEMENTED)
- Apply changes with confirmation
- Log all changes
- Rollback capability

## Safety Checklist

Before changing any parameter:
- [ ] Validate the new value
- [ ] Review impact estimation
- [ ] Check warnings
- [ ] Understand the risk level
- [ ] Have a rollback plan
- [ ] Be in a fresh, alert state

## Change Log Location
`data/config/parameter_changes.log`

## Next Steps (Phase 3)
- Implement actual parameter application
- Add confirmation flow
- Add rollback function
- Add dry-run simulation mode
