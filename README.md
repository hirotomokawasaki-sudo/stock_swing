# stock_swing

Structured trading support and execution-control system for U.S. stocks and ETFs.

## Current scope
- U.S. stocks / ETFs
- Event-driven swing trading
- Short-term momentum / breakout
- Research and paper modes first
- OpenClaw-assisted orchestration
- Deterministic risk and execution gates

## Not in scope for initial build
- Options as a core strategy
- Futures
- Margin-dependent strategies
- HFT / tick-level competition
- LLM-only autonomous execution

## Read first
1. `MUSTREAD_NAVIGATION.md`
2. `GOVERNANCE.md`
3. `RUNTIME_MODES.md`
4. `docs/architecture/SYSTEM_OVERVIEW.md`

## Quick start
1. Copy `.env.example` to `.env`
2. Fill API keys
3. Set `config/runtime/current_mode.yaml` to `research`
4. Run source healthcheck CLI
5. Run raw ingestion in research mode
6. Validate normalized samples and schema contracts
