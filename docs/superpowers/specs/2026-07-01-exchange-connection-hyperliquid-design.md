# Exchange Connection + Hyperliquid Default — Design

**Date:** 2026-07-01
**Status:** Approved (design); pending spec review → implementation plan

## Goal

Let the operator connect the bot to a real exchange from the dashboard: enter credentials in Settings (stored OS-encrypted), pick the exchange, and trade. Make **Hyperliquid** the default exchange with full live-trading support (spot), keeping **Binance** selectable.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Credential storage | **OS-encrypted** via Electron `safeStorage` — no plaintext on disk, never returned to the renderer |
| Hyperliquid scope | **Full live trading now** (spot order placement, end-to-end) |
| Testnet | **Yes** — a mainnet/testnet toggle; the live path is verified on testnet first |
| Exchanges | **Both**, Hyperliquid as default; the credential form adapts per exchange |

## Grounding facts (ccxt 4.5.60)

- Hyperliquid requires `walletAddress` + `privateKey` (NOT `apiKey`/`secret`).
- It quotes in **USDC** — the pair is `BTC/USDC`, not `BTC/USDT`. USDT watchlists won't resolve.
- It has spot (299) and swap/perp (452) markets. The long-only **spot** model works (`BTC/USDC` spot); no forced perps.
- `fetchOHLCV` works, so paper/backtest/prices need **no** credentials.

## Safety requirements (non-negotiable, built in)

- **Agent/API wallet only.** The Settings UI states inline that the Hyperliquid key must be an **approved agent wallet** private key — one that can *trade but not withdraw*. A raw main-wallet key controls the whole balance; Hyperliquid has no CEX-style withdrawal-disable.
- **Testnet default on first run**, so an unconfigured/new setup can't fire mainnet orders.
- **`LIVE_TRADING_ARMED` two-switch unchanged.** Real orders still require `mode: live` **and** `LIVE_TRADING_ARMED=yes`; the desktop app only arms the explicit execute-suggestion path.
- Secrets are **never** sent to the renderer; the UI only learns set/not-set.

## Architecture — credential flow

```
Settings (renderer)
  │  set-exchange-config { activeExchange, testnet, creds }   (secrets travel main-ward only)
  ▼
main process ── safeStorage.encryptString ──▶ <userData>/exchange-creds.enc   (outside the repo)
  │
  │  on every engine spawn: decrypt → inject ACTIVE exchange's creds as env vars
  ▼
engine (python) ── reads creds from env (as today) ──▶ ccxt
```

The renderer's `get-exchange-config` returns non-secret fields (active exchange, testnet, and a boolean per secret: set / not-set) — never the secret values.

## Slice 1 — Secure credential store (desktop main)

- **`desktop/src/main/secrets.ts`**: `safeStorage.encryptString/decryptString`. Blob:
  `{ activeExchange: "hyperliquid"|"binance", testnet: boolean, binance: {apiKey, secret}, hyperliquid: {walletAddress, privateKey} }`
  stored at `app.getPath("userData")/exchange-creds.enc`.
- **IPCs**: `get-exchange-config` (non-secret view), `set-exchange-config` (merge + encrypt + write).
- **Spawn injection** (`engine.ts`): before spawning, decrypt and add env vars for the **active** exchange only —
  Binance → `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`; Hyperliquid → `HYPERLIQUID_WALLET_ADDRESS` / `HYPERLIQUID_PRIVATE_KEY`; plus `EXCHANGE_TESTNET=1` when testnet. Injection composes with the existing `pinnedEnv` (unarmed spawns still force `LIVE_TRADING_ARMED=no`).
- **Keychain unavailable** (`safeStorage.isEncryptionAvailable()` false, e.g. no Linux keyring): saving is **blocked** with a clear message — never silently fall back to plaintext.
- **Tests**: encrypt/decrypt round-trip (mocked safeStorage), get-view redacts secrets, spawn-env maps the active exchange only.

## Slice 2 — Engine: multi-exchange creds + Hyperliquid default

- **`engine/config.py`**: per-exchange credential loading + a `testnet: bool`. Env-name indirection like the existing `exchange_api_key_env` pattern, extended with `exchange_wallet_env` / `exchange_private_key_env` and `EXCHANGE_TESTNET`. New `cfg` fields: `exchange_wallet`, `exchange_private_key`, `testnet`.
- **`engine/market.py` `make_exchange`**: for `hyperliquid`, build with `{walletAddress, privateKey}` and call `set_sandbox_mode(True)` when testnet; for others, `{apiKey, secret}`. Public-data (paper/backtest) path stays keyless.
- **`engine/config.yaml`**: default `exchange: hyperliquid`, `symbols: [BTC/USDC, ETH/USDC]`.
- **Symbol quote handling**: the watchlist (`symbols.json`) and `config.yaml` must use the exchange's quote. Slice 2 resolves the default USDC set against HL spot `load_markets` (watchlist coins that have an `X/USDC` spot market; fallback to a curated core: BTC/ETH/SOL/…/USDC). A symbol whose quote doesn't exist on the active exchange is skipped with a logged reason (already the per-symbol fail-safe) — surfaced so the user can fix their Pairs list.
- **Tests**: per-exchange env→cfg mapping, `make_exchange` hyperliquid args + testnet sandbox, USDC default resolution, unknown-quote symbol skip.

## Slice 3 — Hyperliquid live order placement (spot) + testnet bring-up

- Wire the live execution path (`market.create_order` / `_run_live`) for HL **spot**: HL orders carry a price (limit with slippage / market-as-limit), rounded to HL precision, skipped below HL min notional — mirroring the existing Binance sizing/rounding gate.
- Gated by the unchanged two-switch + `data/HALT` kill switch.
- **Verification on testnet first** (`set_sandbox_mode`): a real buy then sell on Hyperliquid testnet, asserting fills reconcile into `data/live_meta.json` + `state.json` mirror. **Depends on the operator providing testnet agent-wallet creds + testnet funds.**
- **Tests**: HL order-arg building (side/amount/price/params, precision, min notional) as pure unit tests; testnet buy/sell as a gated integration check.

## Slice 4 — Settings "Exchange" UI (renderer)

- New **Exchange** section in Settings: exchange dropdown (Hyperliquid default), credential inputs that **adapt per exchange** (Binance: API key/secret; Hyperliquid: wallet address/private key — masked), a **testnet** toggle, the inline **agent-wallet-only** safety note, and Save.
- **Test connection** button: spawns a read-only balance fetch and reports success/failure (no order).
- Displays **set / not-set** per field, never the stored secret. Editing a "set" field replaces it; leaving it blank keeps the stored value.
- **Tests (Playwright)**: section renders, fields swap with the exchange dropdown, testnet toggle, save calls `set-exchange-config` with the right shape, secrets shown as set/not-set.

## Data at rest / gitignore

- `exchange-creds.enc` lives in Electron `userData` (outside the repo) — not committed by construction. No new secret files under the repo. `.env` remains supported for headless/cron runs (engine reads env either way).

## Out of scope (this feature)

- Perps/leverage trading on Hyperliquid (spot only for now).
- Packaged-app Python bundling (still deferred, tracked separately).
- Automatic USDT→USDC watchlist migration beyond the default seed + skip-and-warn on unknown-quote symbols.

## Verification dependencies

- Slice 3's live-path verification needs **Hyperliquid testnet** agent-wallet address + private key and testnet balance from the operator. Slices 1, 2, 4 are fully verifiable without real credentials.
