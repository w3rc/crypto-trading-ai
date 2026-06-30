import json as _json
import pandas as pd
from engine import execute
from engine.config import Config, RiskConfig, LLMConfig, SentimentConfig
from engine.models import Decision, Fill
from engine.state import save_pending, load_state


# self-contained fakes (tests/ is not a package — do not import from test_bot)
def _cfg(tmp_path, symbols=("BTC/USDT",)):
    return Config(exchange="x", symbols=list(symbols), timeframe="15m",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                  sentiment=SentimentConfig(enabled=False))


def _df():
    closes = [100.0 + i for i in range(60)]
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes,
                         "volume": [5.0] * 60})


class FakeMarket:
    def make_exchange(self, name): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
    def fetch_price(self, ex, sym): return 159.0


class _LiveMarket:
    """Fake live market; records create_order calls and returns a closed fill."""
    def __init__(self, cash=5000.0, qty=None, price=159.0):
        self.cash, self.qty, self.price = cash, qty or {}, price
        self.orders = []
    def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
    def fetch_price(self, ex, sym): return self.price
    def fetch_balance(self, ex, symbols): return self.cash, {s: self.qty.get(s, 0.0) for s in symbols}
    def clamp_to_market(self, ex, sym, qty, price): return qty
    def create_order(self, ex, sym, side, qty, ref_price, ts):
        self.orders.append((sym, side, qty))
        return Fill(sym, side, qty, ref_price, qty * ref_price * 0.001, ts)


def _strat(decision):
    return lambda features, position, cash, cfg: decision


def _seed_pending(tmp_path, sym="BTC/USDT", action="buy", size=1.0):
    save_pending({sym: {"ts": "t", "action": action, "size": size, "reason": "r", "price": 159.0}},
                 str(tmp_path))


def test_execute_paper_fills_and_clears_pending(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "paper"; cfg.auto_execute = False
    _seed_pending(tmp_path)
    # the stored buy is forced through run_once; the strategy (hybrid/LLM) is never called
    code = execute.main("BTC/USDT", cfg=cfg, market=FakeMarket())
    assert code == 0
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0                 # the stored buy executed
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend                           # cleared after execution


def test_execute_shadow_mode_refuses(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "shadow"
    _seed_pending(tmp_path)
    assert execute.main("BTC/USDT", cfg=cfg, market=FakeMarket()) == 2
    assert not (tmp_path / "trades.csv").exists()


def test_execute_live_unarmed_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ARMED", raising=False)
    cfg = _cfg(tmp_path); cfg.mode = "live"
    _seed_pending(tmp_path)
    assert execute.main("BTC/USDT", cfg=cfg, market=_LiveMarket()) == 3


def test_execute_no_pending_returns_4(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "paper"
    assert execute.main("BTC/USDT", cfg=cfg, market=FakeMarket()) == 4


def test_execute_live_armed_places_real_order(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"; cfg.auto_execute = False
    _seed_pending(tmp_path)
    mk = _LiveMarket()
    code = execute.main("BTC/USDT", cfg=cfg, market=mk)
    assert code == 0
    assert len(mk.orders) == 1 and mk.orders[0][1] == "buy"  # a REAL order placed
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend
