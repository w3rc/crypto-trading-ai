# Exchange Credentials — Slice 3: Hyperliquid spot order placement + testnet bring-up (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the engine's existing live-order path place real Hyperliquid **spot** orders correctly, and verify the full buy→sell round-trip on Hyperliquid **testnet** before any mainnet use.

**Architecture:** The engine already routes every real order through `market.create_order` (the single order-placement call) after `market.clamp_to_market` (precision + min-notional). Both are exchange-agnostic ccxt. Hyperliquid has **no native market order** — ccxt (`createMarketOrder: True`, `defaultSlippage: 0.05`) builds an aggressive limit from a reference price. This slice makes `create_order` pass that reference price for Hyperliquid, hardens the precision/min-notional gate for HL market data, and adds a gated testnet round-trip verification.

**Tech Stack:** Python, ccxt 4.5.60 (`hyperliquid`), pytest. Builds on Slices 1–2 (env-injected wallet creds, `make_exchange` HL wallet-auth + `set_sandbox_mode`, HL/USDC default).

Spec: `docs/superpowers/specs/2026-07-01-exchange-connection-hyperliquid-design.md`.

## Global Constraints

- The two-switch arming is unchanged: real orders require `mode: live` **and** `LIVE_TRADING_ARMED=yes`; `data/HALT` stops instantly; paper/backtest never place orders.
- Long-only **spot** only (no perps/leverage).
- `create_order` stays the ONLY order-placement call in the engine.
- Existing non-Hyperliquid behavior (Binance) must not change — a true-market venue must still receive a plain market order.
- **Testnet-first:** the live round-trip is verified against Hyperliquid testnet (`set_sandbox_mode` from Slice 2) with an **agent wallet** (trade-only). No mainnet order is placed as part of this slice.

## Verification dependency (read before starting)

Task 3 (live round-trip) requires the operator to provide **Hyperliquid testnet** agent-wallet credentials (`HYPERLIQUID_WALLET_ADDRESS` / `HYPERLIQUID_PRIVATE_KEY` for testnet) and a small testnet USDC balance. Tasks 1–2 are fully unit-testable offline without any credentials. Do not attempt Task 3 without those credentials — mark it BLOCKED and stop.

## Open question this slice resolves (on testnet, Task 3)

Whether `exchange.create_order(symbol, "market", side, qty, ref_price)` is accepted by ccxt-hyperliquid as-is, or needs an explicit slippage param / limit type. Task 1 implements the ref-price-for-HL approach (defensive, unit-tested against a mock); Task 3 confirms it against the real testnet and, if ccxt rejects it, is the point where the exact call is adjusted (documented as a Task-3 finding, then Task 1's mock updated to match).

---

### Task 1: Pass a reference price for Hyperliquid market orders

**Files:**
- Modify: `engine/market.py` (`create_order`, currently near lines 52-71)
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: nothing new (uses the `ref_price` already passed to `create_order`).
- Produces: unchanged `create_order(exchange, symbol, side, qty, ref_price, ts) -> Fill` signature; internal behavior branches on `exchange.id`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_market.py` (a fake exchange that records the `create_order` args and returns a closed order):

```python
class RecordingExchange:
    id = "binance"
    def __init__(self, exid="binance"):
        self.id = exid
        self.calls = []
    def create_order(self, symbol, otype, side, qty, price=None, params=None):
        self.calls.append({"symbol": symbol, "type": otype, "side": side,
                           "qty": qty, "price": price, "params": params})
        return {"status": "closed", "filled": qty, "average": price or 100.0,
                "fee": {"cost": 0.0}, "id": "1"}


def test_create_order_hyperliquid_passes_reference_price():
    ex = RecordingExchange("hyperliquid")
    fill = market.create_order(ex, "BTC/USDC", "buy", 0.5, 60000.0, "2026-07-01T00:00:00Z")
    assert ex.calls[0]["type"] == "market"
    assert ex.calls[0]["price"] == 60000.0     # HL needs the ref price to build its aggressive limit
    assert fill.qty == 0.5


def test_create_order_binance_sends_plain_market_no_price():
    ex = RecordingExchange("binance")
    market.create_order(ex, "BTC/USDT", "sell", 0.5, 60000.0, "2026-07-01T00:00:00Z")
    assert ex.calls[0]["type"] == "market"
    assert ex.calls[0]["price"] is None        # a true-market venue gets no price
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_market.py -q -k create_order`
Expected: FAIL — current `create_order` calls `exchange.create_order(symbol, "market", side, qty)` with no price, so the hyperliquid assertion (`price == 60000.0`) fails.

- [ ] **Step 3: Write the implementation**

In `engine/market.py`, change the first line of `create_order`'s body from:

```python
    o = exchange.create_order(symbol, "market", side, qty)
```

to:

```python
    # Hyperliquid has no native market order — ccxt builds an aggressive limit and needs a
    # reference price; a true-market venue (Binance) takes a plain market order with no price.
    price_arg = ref_price if getattr(exchange, "id", "") == "hyperliquid" else None
    o = exchange.create_order(symbol, "market", side, qty, price_arg)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_market.py -q`
Expected: PASS — both new tests green; the existing `create_order` reconciliation tests (filled/average/fee, re-poll) still pass because `RecordingExchange` returns a closed order and the Binance path is unchanged.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add engine/market.py tests/test_market.py
git commit -m "feat(engine): pass reference price for Hyperliquid market orders (no native market type)"
```

---

### Task 2: Harden the precision/min-notional gate for Hyperliquid market data

**Files:**
- Test: `tests/test_market.py` (add coverage; `clamp_to_market` code is expected to already work — this task proves it against HL-shaped market metadata and only changes code if a test fails)

**Interfaces:**
- Consumes: existing `clamp_to_market(exchange, symbol, qty, price) -> float`.
- Produces: no signature change.

- [ ] **Step 1: Write the tests**

Add to `tests/test_market.py` (a fake exchange exposing HL-style `markets` + `amount_to_precision`):

```python
class HLMarketExchange:
    id = "hyperliquid"
    markets = {"BTC/USDC": {"limits": {"amount": {"min": 0.001}, "cost": {"min": 10.0}},
                            "precision": {"amount": 0.0001}}}
    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"                     # 4-dp amount precision


def test_clamp_rounds_to_hl_amount_precision():
    ex = HLMarketExchange()
    assert market.clamp_to_market(ex, "BTC/USDC", 0.123456, 60000.0) == 0.1235


def test_clamp_zero_below_hl_min_amount():
    ex = HLMarketExchange()
    assert market.clamp_to_market(ex, "BTC/USDC", 0.0005, 60000.0) == 0.0   # below min amount 0.001


def test_clamp_zero_below_hl_min_cost():
    ex = HLMarketExchange()
    # 0.0002 BTC * 60000 = $12 > $10 min cost, OK; 0.0001 * 60000 = $6 < $10 -> 0
    assert market.clamp_to_market(ex, "BTC/USDC", 0.0001, 60000.0) == 0.0
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_market.py -q -k clamp`
Expected: PASS immediately — `clamp_to_market` already reads `markets[symbol]["limits"]` and calls `amount_to_precision`, which is exchange-agnostic. If any assertion fails, the fix is in `clamp_to_market` (report the exact failure); do not weaken the test.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_market.py
git commit -m "test(engine): clamp_to_market covers Hyperliquid precision + min-notional"
```

---

### Task 3: Testnet round-trip verification (GATED — requires operator testnet credentials)

**Files:**
- No source changes expected. If the live testnet run reveals that ccxt-hyperliquid rejects the Task-1 call shape, THIS is where `engine/market.py:create_order` is adjusted to the confirmed call, Task-1's mock test updated to match, and both re-committed.

**Precondition:** The operator has supplied Hyperliquid **testnet** agent-wallet creds and a small testnet USDC balance. If not, STOP and report BLOCKED — do not fabricate or skip.

- [ ] **Step 1: Point the engine at testnet with the agent wallet**

Set env for a throwaway run (do NOT commit these):
```bash
export HYPERLIQUID_WALLET_ADDRESS=<testnet agent wallet>
export HYPERLIQUID_PRIVATE_KEY=<testnet agent private key>
export EXCHANGE_TESTNET=1
export LIVE_TRADING_ARMED=yes
```
Confirm `set_sandbox_mode` is active:
```bash
python -c "import ccxt; e=ccxt.hyperliquid({'walletAddress':'x','privateKey':'y'}); e.set_sandbox_mode(True); print(e.urls['api'])"
```
Expected: prints the `hyperliquid-testnet.xyz` URLs.

- [ ] **Step 2: Confirm the balance path reads the testnet account**

Run a read-only balance check via the engine's `fetch_balance` against a testnet exchange built by `make_exchange("hyperliquid", "live", wallet=..., private_key=..., testnet=True)`.
Expected: returns the testnet USDC cash + any base balances without error (proves auth works).

- [ ] **Step 3: Place a small live BUY on testnet through the real engine path**

With `mode: live` in `data/control.json` (or config), one symbol `BTC/USDC`, and a size above HL min-notional, run one live cycle (`python -m engine.bot`) — or drive `engine.execute BTC/USDC` for a single armed order.
Expected: a real testnet fill; `data/live_meta.json` records entry price + stop; `data/state.json` mirror shows the position; the trade/decision logs show `executed: true`.

- [ ] **Step 4: Place the matching SELL on testnet**

Trigger the exit (stop-loss or a forced sell decision) and run another cycle.
Expected: the position closes on testnet; balances reconcile (the engine re-reads real balances next cycle — exchange is the source of truth).

- [ ] **Step 5: If ccxt rejected the Task-1 call, fix and re-verify**

If Step 3 raised a ccxt error about the order shape (e.g. price/params required differently), adjust `engine/market.py:create_order` to the confirmed working call, update the Task-1 mock test to assert the confirmed shape, run `python -m pytest tests/test_market.py -q`, and repeat Step 3.

- [ ] **Step 6: Record the verification + clean up**

Append the testnet round-trip evidence (buy fill, sell fill, balance reconciliation) to the task report. Unset the throwaway env vars. Commit only any source fix from Step 5:
```bash
git add engine/market.py tests/test_market.py   # only if Step 5 changed them
git commit -m "fix(engine): adjust Hyperliquid order call to confirmed testnet shape"   # only if needed
```

---

## Self-Review

**Spec coverage (Slice 3 items):**
- Wire live execution for HL spot (price-carrying order) → Task 1. ✓
- HL precision + min-notional gate → Task 2 (proves the existing `clamp_to_market`). ✓
- Gated by the two-switch + `data/HALT` → unchanged; the live path already enforces it (`engine/bot.py` `_run_live`). ✓
- Verified on testnet first (buy then sell, reconcile) → Task 3 (gated on operator creds). ✓

**Placeholder scan:** Tasks 1–2 carry complete code. Task 3 is inherently a live-verification task (no unit code); its one conditional source change (Step 5) is contingent on a testnet finding and is fully specified as "adjust to the confirmed call + update the mock." No vague "handle edge cases." ✓

**Type consistency:** `create_order(exchange, symbol, side, qty, ref_price, ts)` and `clamp_to_market(exchange, symbol, qty, price)` signatures are unchanged; the mock exchanges match the real ccxt method shapes used by the code. ✓

**Out of scope:** perps/leverage; the Settings UI (Slice 4); mainnet order placement.
