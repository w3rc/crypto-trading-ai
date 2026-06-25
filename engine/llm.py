import json

from engine.models import Decision, Position

SYSTEM_PROMPT = (
    "You are a disciplined crypto spot trader. You may only go long or flat "
    "(no shorting). Given indicator values and the current position, decide ONE "
    "action. Respond with ONLY a JSON object, no prose, of the form: "
    '{"action": "buy"|"sell"|"hold", "size": <0..1>, "reason": "<short>", '
    '"stop": <price or null>}. "size" is the fraction of equity to deploy on a '
    "buy, or the fraction of the held position to sell. Be conservative; prefer "
    "hold when the signal is weak."
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
            client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
        kwargs = dict(
            model=cfg.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
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
