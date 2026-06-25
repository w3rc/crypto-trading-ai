from engine import llm
from engine.models import Decision


def hybrid(features, position, cash, cfg) -> Decision:
    """Indicators + LLM judgment — the v1 behavior, unchanged."""
    return llm.decide(features, position, cash, cfg.llm)


STRATEGIES = {"hybrid": hybrid}


def get(name):
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name]
