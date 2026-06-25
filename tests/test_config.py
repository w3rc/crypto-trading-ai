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
