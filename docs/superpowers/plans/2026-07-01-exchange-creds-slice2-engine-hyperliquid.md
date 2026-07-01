# Exchange Credentials — Slice 2: Engine multi-exchange creds + Hyperliquid default (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the Python engine to authenticate to Hyperliquid (wallet address + private key) and Binance (api key/secret), honor a testnet flag, and default to Hyperliquid with USDC spot symbols — all fed by the env vars Slice 1 injects.

**Architecture:** `config.py` gains per-exchange credential fields + a `testnet` flag, loaded from env with the existing `*_env` indirection. `market.make_exchange` branches on the exchange name for the credential shape and applies `set_sandbox_mode` when testnet. `config.yaml` default flips to `hyperliquid` / USDC. Paper and backtest stay keyless on mainnet public data.

**Tech Stack:** Python, ccxt 4.5.60 (`hyperliquid` requires `walletAddress`+`privateKey`, quotes USDC, supports `15m` OHLCV keyless, `set_sandbox_mode(True)` → testnet URLs — all verified live), pytest.

Spec: `docs/superpowers/specs/2026-07-01-exchange-connection-hyperliquid-design.md`. Slice 1 (merged) injects these env vars at engine spawn: `HYPERLIQUID_WALLET_ADDRESS`, `HYPERLIQUID_PRIVATE_KEY`, `EXCHANGE_API_KEY`, `EXCHANGE_API_SECRET`, `EXCHANGE_TESTNET` (`"1"`/`"0"`).

## Global Constraints

- Env var names, exact (Slice 1 injects these; the config loader's indirection defaults to them): `HYPERLIQUID_WALLET_ADDRESS`, `HYPERLIQUID_PRIVATE_KEY`, `EXCHANGE_API_KEY`, `EXCHANGE_API_SECRET`, `EXCHANGE_TESTNET`.
- Credentials attach ONLY for `mode in ("shadow", "live")` — never for paper.
- Hyperliquid credential shape is `walletAddress` + `privateKey`; every other exchange uses `apiKey` + `secret`.
- `testnet` applies whenever the flag is set (`set_sandbox_mode(True)`), independent of mode.
- Paper and backtest callers stay keyless and on **mainnet** public data (better liquidity/history) — do NOT pass testnet or creds to `engine/backtest.py:204` or the paper path `engine/bot.py:59`.
- Long-only spot preserved; Hyperliquid spot uses USDC (`BTC/USDC`).
- Do not change mode logic or the two-switch arming.

## Note on spec deviation (USDC symbol resolution)

The spec's Slice 2 text says "resolve the default USDC set against HL spot `load_markets`." Doing that at config-load time means a network round-trip on every load — impractical and fragile. This plan instead ships a **curated USDC default** (`[BTC/USDC, ETH/USDC]`, mirroring today's 2-symbol default) and relies on the engine's existing per-symbol skip-and-warn (`engine/bot.py` wraps each symbol in try/except and logs `skip <sym>`) for any unknown-quote symbol in a user's watchlist. Dynamic market resolution / Pairs-tab validation is deferred to the Slice 4 UI. (Flag raised to the human at plan review.)

---

### Task 1: Config — per-exchange credentials + testnet flag

**Files:**
- Modify: `engine/config.py` (Config dataclass near lines 73-74; loader near lines 188-189; add a testnet helper near `_mode_override`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.exchange_wallet: str`, `Config.exchange_private_key: str`, `Config.testnet: bool`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_load_config_exchange_credentials_and_testnet(monkeypatch, tmp_path):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "0xabc")
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "0xpk")
    monkeypatch.setenv("EXCHANGE_API_KEY", "bkey")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "bsec")
    monkeypatch.setenv("EXCHANGE_TESTNET", "1")
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "engine", "config.yaml")
    monkeypatch.chdir(tmp_path)
    cfg = load_config(cfg_path)
    assert cfg.exchange_wallet == "0xabc"
    assert cfg.exchange_private_key == "0xpk"
    assert cfg.exchange_api_key == "bkey"
    assert cfg.exchange_secret == "bsec"
    assert cfg.testnet is True


def test_testnet_defaults_false_and_creds_empty_without_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    for v in ("EXCHANGE_TESTNET", "HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_PRIVATE_KEY"):
        monkeypatch.delenv(v, raising=False)
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "engine", "config.yaml")
    monkeypatch.chdir(tmp_path)
    cfg = load_config(cfg_path)
    assert cfg.testnet is False
    assert cfg.exchange_wallet == ""
    assert cfg.exchange_private_key == ""


def test_exchange_testnet_zero_is_false(monkeypatch, tmp_path):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    monkeypatch.setenv("EXCHANGE_TESTNET", "0")
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "engine", "config.yaml")
    monkeypatch.chdir(tmp_path)
    assert load_config(cfg_path).testnet is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py::test_load_config_exchange_credentials_and_testnet tests/test_config.py::test_testnet_defaults_false_and_creds_empty_without_env tests/test_config.py::test_exchange_testnet_zero_is_false -q`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'exchange_wallet'` (and `testnet`).

- [ ] **Step 3: Write the implementation**

In `engine/config.py`, add to the `Config` dataclass right after `exchange_secret` (near line 74):

```python
    exchange_wallet: str = field(default="", repr=False)
    exchange_private_key: str = field(default="", repr=False)
    testnet: bool = False
```

Add this helper next to `_mode_override` (near line 77):

```python
def _testnet_flag(default: bool) -> bool:
    """EXCHANGE_TESTNET in env wins ('1' -> True, anything else -> False); absent -> config default."""
    v = os.environ.get("EXCHANGE_TESTNET")
    return v == "1" if v is not None else default
```

In the `load_config` return (after the `exchange_secret=...` line near 189), add:

```python
        exchange_wallet=os.environ.get(raw.get("exchange_wallet_env", "HYPERLIQUID_WALLET_ADDRESS"), ""),
        exchange_private_key=os.environ.get(raw.get("exchange_private_key_env", "HYPERLIQUID_PRIVATE_KEY"), ""),
        testnet=_testnet_flag(bool(raw.get("testnet", False))),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS (new tests green; existing config tests unaffected — they don't touch the new fields).

- [ ] **Step 5: Commit**

```bash
git add engine/config.py tests/test_config.py
git commit -m "feat(engine): load per-exchange credentials + testnet flag from env"
```

---

### Task 2: market.make_exchange — multi-exchange credential shape + testnet

**Files:**
- Modify: `engine/market.py:20-25` (`make_exchange`)
- Modify: `engine/bot.py:164-165` (shadow path) and `engine/bot.py:281-282` (live path) — the two credentialed call sites
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes (Task 1): `Config.exchange_wallet`, `Config.exchange_private_key`, `Config.testnet`.
- Produces: `make_exchange(name, mode="paper", api_key="", secret="", *, wallet="", private_key="", testnet=False)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_market.py`:

```python
def test_make_exchange_hyperliquid_live_loads_wallet_creds():
    ex = market.make_exchange("hyperliquid", "live", wallet="0xabc", private_key="0xpk")
    assert ex.walletAddress == "0xabc"
    assert ex.privateKey == "0xpk"


def test_make_exchange_binance_live_loads_api_creds():
    ex = market.make_exchange("binance", "live", "KEY", "SEC")
    assert ex.apiKey == "KEY"
    assert ex.secret == "SEC"


def test_make_exchange_paper_has_no_credentials():
    ex = market.make_exchange("hyperliquid")   # paper -> keyless public data
    assert not getattr(ex, "walletAddress", "")
    assert not getattr(ex, "privateKey", "")


def test_make_exchange_testnet_uses_sandbox_urls():
    ex = market.make_exchange("hyperliquid", "live", wallet="0xabc", private_key="0xpk", testnet=True)
    assert "testnet" in str(ex.urls["api"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_market.py -q -k "make_exchange"`
Expected: FAIL — `TypeError: make_exchange() got an unexpected keyword argument 'wallet'` (and hyperliquid creds not set).

- [ ] **Step 3: Write the implementation**

Replace `engine/market.py:20-25` with:

```python
def make_exchange(name: str, mode: str = "paper", api_key: str = "", secret: str = "",
                  *, wallet: str = "", private_key: str = "", testnet: bool = False):
    opts = {"enableRateLimit": True}
    if mode in ("shadow", "live"):
        if name == "hyperliquid":                 # DEX: wallet address + agent-wallet private key
            opts["walletAddress"] = wallet
            opts["privateKey"] = private_key
        else:                                      # CEX: api key + secret
            opts["apiKey"] = api_key
            opts["secret"] = secret
    ex = getattr(ccxt, name)(opts)
    if testnet:                                    # public + private URLs -> the exchange's testnet
        ex.set_sandbox_mode(True)
    return ex
```

In `engine/bot.py`, update the shadow call site (near line 164) to pass the new creds:

```python
        exchange = market.make_exchange(cfg.exchange, cfg.mode,
                                        cfg.exchange_api_key, cfg.exchange_secret,
                                        wallet=cfg.exchange_wallet, private_key=cfg.exchange_private_key,
                                        testnet=cfg.testnet)
```

And the live call site (near line 281):

```python
        exchange = market.make_exchange(cfg.exchange, "live",
                                        cfg.exchange_api_key, cfg.exchange_secret,
                                        wallet=cfg.exchange_wallet, private_key=cfg.exchange_private_key,
                                        testnet=cfg.testnet)
```

Leave the paper/backtest call sites unchanged: `engine/backtest.py:204` and `engine/bot.py:59` stay `make_exchange(cfg.exchange)` (keyless, mainnet).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_market.py -q`
Expected: PASS (new make_exchange tests green; existing `test_make_exchange_shadow_loads_credentials` still passes — binance branch unchanged).

- [ ] **Step 5: Run the full suite (caller changes are cross-file)**

Run: `python -m pytest -q`
Expected: all pass — the paper callers are untouched and the new kwargs are keyword-only with empty defaults, so `make_exchange(cfg.exchange)` is unaffected.

- [ ] **Step 6: Commit**

```bash
git add engine/market.py engine/bot.py tests/test_market.py
git commit -m "feat(engine): make_exchange supports hyperliquid wallet creds + testnet sandbox"
```

---

### Task 3: Default to Hyperliquid + USDC symbols

**Files:**
- Modify: `engine/config.yaml:1-2` (exchange + symbols) and the commented env hints near lines 11-12
- Modify: `tests/test_config.py:9-10` (the default assertions in `test_load_config_defaults`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: default config where `exchange == "hyperliquid"` and `symbols == ["BTC/USDC", "ETH/USDC"]`.

- [ ] **Step 1: Update the failing assertion first (TDD: change the expectation, watch it fail)**

In `tests/test_config.py`, change lines 9-10 of `test_load_config_defaults` from:

```python
    assert cfg.exchange == "binance"
    assert cfg.symbols == ["BTC/USDT", "ETH/USDT"]
```

to:

```python
    assert cfg.exchange == "hyperliquid"
    assert cfg.symbols == ["BTC/USDC", "ETH/USDC"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_config.py::test_load_config_defaults -q`
Expected: FAIL — still loads `binance` / `["BTC/USDT", "ETH/USDT"]` from the old config.yaml.

- [ ] **Step 3: Update config.yaml**

In `engine/config.yaml`, change lines 1-2 from:

```yaml
exchange: binance
symbols: [BTC/USDT, ETH/USDT]
```

to:

```yaml
exchange: hyperliquid
symbols: [BTC/USDC, ETH/USDC]     # Hyperliquid quotes USDC, not USDT
```

And update the commented env hints (near lines 11-12) from:

```yaml
# exchange_api_key_env: EXCHANGE_API_KEY      # env var holding a READ-ONLY exchange key (shadow)
# exchange_secret_env: EXCHANGE_API_SECRET
```

to:

```yaml
# Credentials come from env (the desktop Settings panel injects them; or set them in .env):
#   Hyperliquid: HYPERLIQUID_WALLET_ADDRESS / HYPERLIQUID_PRIVATE_KEY  (use an AGENT wallet — trade-only, no withdrawals)
#   Binance:     EXCHANGE_API_KEY / EXCHANGE_API_SECRET
#   EXCHANGE_TESTNET=1 routes shadow/live to the exchange testnet. Override the env-var NAMES with
#   exchange_wallet_env / exchange_private_key_env / exchange_api_key_env / exchange_secret_env if needed.
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS — `test_load_config_defaults` now sees `hyperliquid` / USDC.

- [ ] **Step 5: Run the full suite (guard against other assumptions of the old default)**

Run: `python -m pytest -q`
Expected: all pass. `tests/test_execute.py` and others pass symbols explicitly to their own configs, so they are unaffected. If any test fails because it assumed the binance/USDT default, fix that test's expectation to match the new default (do not revert config.yaml).

- [ ] **Step 6: Verify a real Hyperliquid fetch works with the new default (no keys needed)**

Run:
```bash
python -c "import ccxt; e=ccxt.hyperliquid(); rows=e.fetch_ohlcv('BTC/USDC','15m',limit=5); print('rows', len(rows), 'last', rows[-1][4])"
```
Expected: prints `rows 5 last <a price>` — confirms paper/backtest on the new default works keyless.

- [ ] **Step 7: Commit**

```bash
git add engine/config.yaml tests/test_config.py
git commit -m "feat(engine): default to Hyperliquid with USDC spot symbols"
```

---

## Self-Review

**Spec coverage (Slice 2 items):**
- Per-exchange creds + `testnet` in `config.py` (env-name indirection extended) → Task 1. ✓
- `make_exchange` hyperliquid wallet auth + `set_sandbox_mode` on testnet; Binance apiKey/secret; public path keyless → Task 2. ✓
- `config.yaml` default `hyperliquid` + USDC symbols → Task 3. ✓
- Unknown-quote symbols skip with a logged reason → existing `engine/bot.py` per-symbol try/except (no change needed; noted in the deviation section). ✓
- Dynamic `load_markets` USDC resolution → deliberately deferred (network-on-every-load); curated default + skip-and-warn instead. Flagged to the human. ✓ (deviation, documented)

**Placeholder scan:** No TBD/TODO; every code step carries complete code. ✓

**Type consistency:** `exchange_wallet` / `exchange_private_key` / `testnet` named identically in the dataclass, loader, `make_exchange` kwargs (`wallet` / `private_key` / `testnet`), and both bot.py call sites. Env var names match the Global Constraints and Slice 1's injected names verbatim. ✓

**Out of scope for Slice 2:** Hyperliquid order placement (Slice 3), the Settings UI (Slice 4).
