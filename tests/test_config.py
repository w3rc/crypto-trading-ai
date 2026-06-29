import os
from engine.config import load_config

def test_load_config_defaults(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg = load_config("engine/config.yaml")
    assert cfg.exchange == "binance"
    assert cfg.symbols == ["BTC/USDT", "ETH/USDT"]
    assert cfg.paper_capital == 10000.0
    assert cfg.risk.max_position_pct == 0.25
    assert cfg.llm.model == "z-ai/glm-5.2"
    assert cfg.llm.base_url == "https://ai.myhermes.cloud/v1"
    assert cfg.llm.api_key == "test-key-123"   # resolved from api_key_env
    assert cfg.llm.json_mode is True

def test_load_config_missing_key_is_empty_not_error(monkeypatch):
    monkeypatch.delenv("MYHERMES_API_KEY", raising=False)
    cfg = load_config("engine/config.yaml")
    assert cfg.llm.api_key == ""   # absent key -> "" (tests/mocks don't need it)

def test_strategy_and_rules_load(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg = load_config("engine/config.yaml")
    assert cfg.strategy == "hybrid"
    assert cfg.rules.rsi_buy == 30
    assert cfg.rules.rsi_sell == 70
    assert cfg.rules.buy_size == 0.5

def test_strategy_and_rules_default_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.strategy == "hybrid"     # default when key absent
    assert cfg.rules.rsi_buy == 30      # default rules when block absent

def test_sentiment_loads_from_yaml(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    cfg = load_config("engine/config.yaml")
    assert cfg.sentiment.enabled is True
    assert cfg.sentiment.weights["fear_greed"] == 1.0
    assert cfg.sentiment.cache_ttl["fear_greed"] == 86400
    assert cfg.sentiment.buy_min == -0.2
    assert cfg.sentiment.sell_max == -0.5


def test_sentiment_defaults_when_block_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.sentiment.enabled is True           # default
    assert cfg.sentiment.weights["reddit"] == 1.0  # default weights
    assert cfg.sentiment.buy_min == -0.2


def test_sentiment_partial_override_merges(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
        "sentiment:\n  enabled: false\n  weights: {fear_greed: 2.0}\n  buy_min: 0.1\n"
    )
    cfg = load_config(str(p))
    assert cfg.sentiment.enabled is False
    assert cfg.sentiment.weights["fear_greed"] == 2.0   # overridden
    assert cfg.sentiment.weights["reddit"] == 1.0       # default preserved (merge)
    assert cfg.sentiment.buy_min == 0.1


def test_sentiment_dict_values_coerced_to_float(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
        "sentiment:\n  weights: {fear_greed: 2}\n  cache_ttl: {fear_greed: 100}\n"
    )
    cfg = load_config(str(p))
    assert isinstance(cfg.sentiment.weights["fear_greed"], float)
    assert cfg.sentiment.weights["fear_greed"] == 2.0
    assert isinstance(cfg.sentiment.cache_ttl["fear_greed"], float)
    # untouched defaults are still present and numeric (merge preserved)
    assert cfg.sentiment.weights["reddit"] == 1.0


def test_risk_allow_short_defaults_none(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    cfg = load_config("engine/config.yaml")
    assert cfg.risk.allow_short is None        # auto by default


def test_risk_allow_short_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n  allow_short: true\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    assert load_config(str(p)).risk.allow_short is True

def test_risk_leverage_and_mmr_default(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    cfg = load_config("engine/config.yaml")
    assert cfg.risk.leverage == 1.0                 # opt-in: off by default
    assert cfg.risk.maintenance_margin_pct == 0.005

def test_risk_leverage_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "  leverage: 5\n  maintenance_margin_pct: 0.004\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.risk.leverage == 5.0
    assert cfg.risk.maintenance_margin_pct == 0.004


def _risk_yaml(risk_lines: str) -> str:
    return (
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        f"risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n{risk_lines}"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )


def test_leverage_clamped_to_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(_risk_yaml("  leverage: 500\n"))
    # default mmr 0.005 -> ceiling 0.5/0.005 = 100; an absurd 500x clamps so a long
    # cannot liquidate on open (liq reaches entry above 1/mmr = 200x).
    assert load_config(str(p)).risk.leverage == 100.0


def test_leverage_floored_at_one(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(_risk_yaml("  leverage: 0.5\n"))
    assert load_config(str(p)).risk.leverage == 1.0   # sub-1x is nonsensical -> floored


def test_leverage_ceiling_scales_with_mmr(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(_risk_yaml("  leverage: 100\n  maintenance_margin_pct: 0.02\n"))
    assert load_config(str(p)).risk.leverage == 25.0  # higher mmr -> lower ceiling 0.5/0.02


def test_normal_leverage_passes_through(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(_risk_yaml("  leverage: 5\n"))
    assert load_config(str(p)).risk.leverage == 5.0   # within bounds -> untouched


def test_funding_defaults_off(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    cfg = load_config("engine/config.yaml")
    assert cfg.risk.funding_rate == 0.0                 # opt-in: off by default
    assert cfg.risk.funding_interval_hours == 8.0

def test_funding_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(_risk_yaml("  funding_rate: 0.0001\n  funding_interval_hours: 4\n"))
    cfg = load_config(str(p))
    assert cfg.risk.funding_rate == 0.0001
    assert cfg.risk.funding_interval_hours == 4.0


def test_mode_defaults_paper(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    assert load_config("engine/config.yaml").mode == "paper"

def test_mode_and_credentials_load(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    monkeypatch.setenv("EXCHANGE_API_KEY", "pubkey")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "mode: shadow\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.mode == "shadow"
    assert cfg.exchange_api_key == "pubkey"
    assert cfg.exchange_secret == "secret"

def test_credentials_absent_are_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    monkeypatch.delenv("EXCHANGE_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_API_SECRET", raising=False)
    cfg = load_config("engine/config.yaml")
    assert cfg.exchange_api_key == ""
    assert cfg.exchange_secret == ""

def test_credentials_excluded_from_repr():
    from engine.config import Config, RiskConfig, LLMConfig
    cfg = Config(exchange="x", symbols=["BTC/USDT"], timeframe="15m", paper_capital=1000.0,
                 fee_pct=0.001, slippage_pct=0.0005, data_dir="data",
                 risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                 llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                 exchange_api_key="SUPERSECRETKEY", exchange_secret="SUPERSECRETVALUE")
    text = repr(cfg)
    assert "SUPERSECRETKEY" not in text
    assert "SUPERSECRETVALUE" not in text


def _toggle_yaml(data_dir, mode="paper"):
    return (
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\n"
        f"data_dir: {data_dir}\nmode: {mode}\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )

def test_control_json_overrides_mode(tmp_path):
    (tmp_path / "control.json").write_text('{"mode": "live"}')
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper"))
    assert load_config(str(p)).mode == "live"          # control.json wins over config

def test_control_json_invalid_mode_ignored(tmp_path):
    (tmp_path / "control.json").write_text('{"mode": "bogus"}')
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "shadow"))
    assert load_config(str(p)).mode == "shadow"        # invalid -> config mode

def test_control_json_missing_uses_config(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "shadow"))
    assert load_config(str(p)).mode == "shadow"        # no control.json -> config mode

def test_control_json_corrupt_ignored(tmp_path):
    (tmp_path / "control.json").write_text("{not json")
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper"))
    assert load_config(str(p)).mode == "paper"         # corrupt -> config mode


def test_control_json_non_dict_ignored(tmp_path):
    # json.load returns a non-dict (int) -> .get("mode") raises AttributeError -> config mode
    (tmp_path / "control.json").write_text("123")
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "shadow"))
    assert load_config(str(p)).mode == "shadow"        # non-dict -> AttributeError branch -> config mode

def test_interval_seconds_defaults_to_900(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper"))
    assert load_config(str(p)).interval_seconds == 900     # absent -> default

def test_interval_seconds_from_yaml(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper") + "interval_seconds: 300\n")
    assert load_config(str(p)).interval_seconds == 300     # yaml value wins
