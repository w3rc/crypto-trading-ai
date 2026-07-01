from types import SimpleNamespace
from engine import test_connection


def test_reports_ok_when_balance_fetch_succeeds(monkeypatch, capsys):
    cfg = SimpleNamespace(exchange="hyperliquid", symbols=["BTC/USDC"], mode="shadow",
                          exchange_api_key="", exchange_secret="",
                          exchange_wallet="0xabc", exchange_private_key="0xpk", testnet=True)
    monkeypatch.setattr(test_connection, "load_config", lambda: cfg)
    monkeypatch.setattr(test_connection.market, "make_exchange", lambda *a, **k: object())
    monkeypatch.setattr(test_connection.market, "fetch_balance", lambda ex, syms: (100.0, {}))
    assert test_connection.main() == 0
    assert "ok" in capsys.readouterr().out.lower()


def test_reports_failure_when_fetch_raises(monkeypatch, capsys):
    cfg = SimpleNamespace(exchange="hyperliquid", symbols=["BTC/USDC"], mode="shadow",
                          exchange_api_key="", exchange_secret="",
                          exchange_wallet="", exchange_private_key="", testnet=True)
    monkeypatch.setattr(test_connection, "load_config", lambda: cfg)
    monkeypatch.setattr(test_connection.market, "make_exchange", lambda *a, **k: object())
    def boom(ex, syms): raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(test_connection.market, "fetch_balance", boom)
    assert test_connection.main() == 1
    assert "401" in capsys.readouterr().out
