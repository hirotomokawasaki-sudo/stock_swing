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
3. Set `config/runtime/current_mode.yaml` to `research` or `paper` depending on intended mode
4. Create virtual environment: `python3 -m venv venv`
5. Activate: `source venv/bin/activate`
6. Install dependencies: `pip install -e .`
7. Run tests: `pytest tests/`
8. For demo trading readiness, run: `./scripts/maintenance/broker_health_check.sh`

## Development workflow
**🚨 CRITICAL: Always commit & push after changes!**

```bash
# After any feature addition or change
git add .
git commit -m "feat: description of changes"
git push origin main
```

## Repository
https://github.com/hirotomokawasaki-sudo/stock_swing.git
