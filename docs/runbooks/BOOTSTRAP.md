# BOOTSTRAP.md

## 1. Initial setup
1. Clone or extract project into `~/stock_swing`
2. Create `.env` from `.env.example`
3. Fill API credentials
4. Verify `config/runtime/current_mode.yaml` is `research`
5. Run config validation
6. Run source healthcheck
7. Run a single-source raw ingestion test
8. Validate normalized sample output

## 2. First implementation order
1. config loader
2. path manager
3. storage paths
4. raw ingestion
5. normalization
6. feature generation
7. strategy signals
8. risk checks
9. decision engine
10. paper execution
