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
