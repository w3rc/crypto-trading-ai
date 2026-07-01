import json
from types import SimpleNamespace

from engine import analyze_sentiment, sentiment


def _cfg(tmp_path, enabled=True):
    return SimpleNamespace(sentiment=SimpleNamespace(enabled=enabled),
                           symbols=["BTC/USDT"], strategy="hybrid", data_dir=str(tmp_path))


def test_analyze_writes_sentiment_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze_sentiment, "load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(sentiment, "breakdown",
                        lambda syms, c: {"BTC/USDT": {"blended": 0.3, "sources": {"fear_greed": 0.3}}})
    analyze_sentiment.main()
    snap = json.loads((tmp_path / "sentiment.json").read_text())
    assert snap["symbols"]["BTC/USDT"]["blended"] == 0.3
    assert snap["strategy"] == "hybrid" and "ts" in snap


def test_analyze_is_noop_when_sentiment_disabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(analyze_sentiment, "load_config", lambda: _cfg(tmp_path, enabled=False))
    analyze_sentiment.main()
    assert not (tmp_path / "sentiment.json").exists()
    assert "disabled" in capsys.readouterr().out
