import pytest
from engine.metrics import max_drawdown, summarize


def test_max_drawdown_peak_to_trough():
    # 100 -> 120 (peak) -> 90 (trough) -> 110 ; dd = 90/120 - 1 = -0.25
    assert max_drawdown([100, 120, 90, 110]) == pytest.approx(-0.25)


def test_max_drawdown_monotonic_up_is_zero():
    assert max_drawdown([100, 110, 120]) == 0.0


def test_max_drawdown_empty_is_zero():
    assert max_drawdown([]) == 0.0


def test_summarize_beats_hold():
    s = summarize(equity=[100, 130], buy_hold=[100, 120], n_trades=3)
    assert s["total_return"] == pytest.approx(0.30)
    assert s["buy_hold_return"] == pytest.approx(0.20)
    assert s["beats_hold"] is True
    assert s["final_equity"] == 130
    assert s["n_trades"] == 3


def test_summarize_loses_to_hold():
    s = summarize(equity=[100, 110], buy_hold=[100, 125], n_trades=1)
    assert s["beats_hold"] is False
