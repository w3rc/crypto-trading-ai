from engine.llm import decide
from engine.config import LLMConfig
from engine.models import Position

CFG = LLMConfig(base_url="x", api_key="x", model="m", json_mode=True)
FEATS = {"price": 100, "rsi": 28, "macd": 1, "macd_signal": 0,
         "ma_fast": 101, "ma_slow": 99, "atr": 2}

class _Msg:    # minimal openai response shape
    def __init__(self, content): self.message = type("M", (), {"content": content})
class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]
class FakeClient:
    def __init__(self, content=None, exc=None):
        self.content, self.exc = content, exc
        self.last_kwargs = None
        self.chat = type("C", (), {"completions": self})()
    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self.exc: raise self.exc
        return _Resp(self.content)

def test_valid_json_returns_decision():
    c = FakeClient(content='{"action":"buy","size":0.5,"reason":"oversold","stop":95}')
    d = decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c)
    assert d.action == "buy" and d.size == 0.5 and d.stop == 95

def test_json_wrapped_in_text_is_extracted():
    c = FakeClient(content='Here is my call:\n{"action":"sell","size":1.0}\nDone.')
    d = decide(FEATS, Position("BTC/USDT", qty=1), 0, CFG, client=c)
    assert d.action == "sell"

def test_malformed_output_is_hold():
    c = FakeClient(content="I think you should buy a lot!")
    assert decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c).action == "hold"

def test_invalid_action_is_hold():
    c = FakeClient(content='{"action":"moon","size":1}')
    assert decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c).action == "hold"

def test_exception_is_hold():
    c = FakeClient(exc=RuntimeError("network down"))
    d = decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c)
    assert d.action == "hold" and "network down" in d.reason

def test_json_mode_true_sets_response_format():
    c = FakeClient(content='{"action":"hold"}')
    decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c)
    assert c.last_kwargs.get("response_format") == {"type": "json_object"}

def test_json_mode_false_omits_response_format():
    cfg2 = LLMConfig(base_url="x", api_key="x", model="m", json_mode=False)
    c = FakeClient(content='{"action":"hold"}')
    decide(FEATS, Position("BTC/USDT"), 10000, cfg2, client=c)
    assert "response_format" not in c.last_kwargs

def test_brace_wrapped_invalid_json_is_hold():
    c = FakeClient(content="My call: { price: 100, action: buy }")  # invalid JSON inside braces
    assert decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c).action == "hold"

def test_constructed_client_uses_neutral_user_agent(monkeypatch):
    # When decide() builds its own client (client=None), it must NOT use the SDK's
    # default "OpenAI/Python" User-Agent — some gateways' WAF/AI-bot rules 403 it.
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = type("C", (), {"completions": self})()
        def create(self, **kwargs):
            return _Resp('{"action":"hold"}')

    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    d = decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=None)
    assert d.action == "hold"
    assert "OpenAI" not in captured["default_headers"]["User-Agent"]

def test_system_prompt_allows_shorting_when_flagged():
    from engine.llm import _system_prompt
    assert "short" in _system_prompt(True).lower()
    assert "only go long" in _system_prompt(False).lower()
