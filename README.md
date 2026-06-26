# Crypto Paper-Trading Bot — Engine

AI-driven crypto **paper-trading** bot (simulated money). One cron cycle:
ccxt data → indicators → LLM decision → risk gate → simulated fill → `data/`.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your real MYHERMES_API_KEY in .env
```

## Run one cycle
```bash
set -a && source .env && set +a
python -m engine.bot
```
Prints each symbol's decision and the cash/equity summary. State lives in
`data/state.json`; trades in `data/trades.csv`.

## Schedule it (cadence = your choice)
```cron
*/15 * * * * cd /path/to/cryptotrading_ai && set -a && . ./.env && set +a && .venv/bin/python -m engine.bot >> data/bot.log 2>&1
```
Change the cron expression to change cadence — hourly, daily, etc.

## Config
Edit `engine/config.yaml` — symbols, capital, risk limits, and the LLM
provider/model. Default: MyHermes AI + `z-ai/glm-5.2`. Swap `base_url` +
`api_key_env` + `model` for OpenRouter or any OpenAI-compatible endpoint.

## Backtesting

Replay a strategy over historical candles and see if it beats buy-and-hold:

```bash
python -m engine.backtest --symbols BTC/USDT,ETH/USDT --timeframe 1h \
  --since 2024-01-01 --strategy indicator_rule
```

Historical candles are fetched once from the exchange and cached under
`data/cache/`. The equity + buy-hold curves are written to
`data/backtest_equity.csv`. Defaults (fees, slippage, risk, capital) come from
`engine/config.yaml`.

`indicator_rule` is the fast, deterministic strategy. Backtesting `hybrid` is
supported but makes one LLM call per candle per symbol (slow + costly) — you'll
get a warning.

## Tests
```bash
python -m pytest -q
```
