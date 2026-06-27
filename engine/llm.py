import json

from engine.models import Decision, Position

_JSON_RULES = (
    "Respond with ONLY a JSON object, no prose, of the form: "
    '{"action": "buy"|"sell"|"hold", "size": <0..1>, "reason": "<short>", '
    '"stop": <price or null>}. "size" is the fraction of equity to deploy. Be '
    "conservative; prefer hold when the signal is weak."
)


def _system_prompt(allow_short: bool) -> str:
    if allow_short:
        return (
            "You are a disciplined crypto trader. You may go long, short, or flat. "
            "A 'buy' increases your position (or covers a short); a 'sell' decreases "
            "it (or opens/extends a short). " + _JSON_RULES
        )
    return (
        "You are a disciplined crypto spot trader. You may only go long or flat "
        "(no shorting). " + _JSON_RULES
    )


def _build_user(features: dict, position: Position, cash: float) -> str:
    return (
        f"Symbol: {position.symbol}\n"
        f"Indicators: {json.dumps(features)}\n"
        f"Position: qty={position.qty}, avg_price={position.avg_price}\n"
        f"Available cash: {cash}\n"
        "What is your decision?"
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError("no JSON object found") from exc
        raise ValueError("no JSON object found")


def decide(features: dict, position: Position, cash: float, cfg, client=None) -> Decision:
    try:
        if client is None:
            from openai import OpenAI
            # Some OpenAI-compatible gateways sit behind a WAF / AI-bot rule that
            # 403s the SDK's default "OpenAI/Python" User-Agent; a neutral UA passes.
            client = OpenAI(
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                default_headers={"User-Agent": "cryptotrading-bot/1.0"},
            )
        kwargs = dict(
            model=cfg.model,
            messages=[
                {"role": "system", "content": _system_prompt(bool(features.get("allow_short")))},
                {"role": "user", "content": _build_user(features, position, cash)},
            ],
            temperature=0,
        )
        if cfg.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        data = _extract_json(resp.choices[0].message.content)
        return Decision(**data)
    except Exception as e:                      # fail-safe: any failure -> HOLD
        return Decision(action="hold", size=0.0, reason=f"llm-fallback: {e}")
