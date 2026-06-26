import csv
import json
import os
import time
import urllib.parse
import urllib.request

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_VADER = SentimentIntensityAnalyzer()
_CACHE = {}          # {(source, symbols): (fetched_ms, {sym: score})}
_FNG_HISTORY = None  # {day_ms: value}, loaded once for backtests

_DAY_MS = 86_400_000


def _coin(symbol):
    return symbol.split("/")[0].upper()


def _clamp(x):
    return max(-1.0, min(1.0, x))


def _http_json(url, headers=None, timeout=6.0):
    req = urllib.request.Request(
        url, headers=headers or {"User-Agent": "cryptotrading-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _vader_score(texts):
    if not texts:
        return None
    scores = [_VADER.polarity_scores(t)["compound"] for t in texts]
    return sum(scores) / len(scores)


# ---- Fear & Greed (alternative.me) — market-wide, the one backtestable source ----

def _read_fng_cache(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as f:
        for row in csv.reader(f):
            out[int(row[0])] = float(row[1])
    return out


def _write_fng_cache(path, hist):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        for day_ms, val in sorted(hist.items()):
            w.writerow([day_ms, val])


def _fng_history(cfg):
    # ponytail: fetched once, cached to disk + a process global; no incremental
    # refresh (the daily series rarely needs the last day or two for a backtest).
    global _FNG_HISTORY
    if _FNG_HISTORY is not None:
        return _FNG_HISTORY
    path = os.path.join("data", "cache", "feargreed.csv")
    hist = _read_fng_cache(path)
    if not hist:
        data = _http_json("https://api.alternative.me/fng/?limit=0",
                          timeout=cfg.sentiment.http_timeout)
        hist = {}
        for d in data["data"]:
            day_ms = (int(d["timestamp"]) // 86400) * 86400 * 1000
            hist[day_ms] = float(d["value"])
        _write_fng_cache(path, hist)
    _FNG_HISTORY = hist
    return hist


def _fng_lookup(hist, day_ms):
    d = day_ms
    for _ in range(8):                 # this day, or the nearest earlier (up to a week)
        if d in hist:
            return hist[d]
        d -= _DAY_MS
    return None


def fear_greed(symbols, cfg, backtest=False, ts_ms=None):
    try:
        if backtest:
            day = (ts_ms // _DAY_MS) * _DAY_MS
            val = _fng_lookup(_fng_history(cfg), day)
            if val is None:
                return {}
        else:
            data = _http_json("https://api.alternative.me/fng/?limit=1",
                              timeout=cfg.sentiment.http_timeout)
            val = float(data["data"][0]["value"])
        score = (val - 50) / 50.0      # 0->-1, 50->0, 100->+1
        return {s: score for s in symbols}
    except Exception:
        return {}                      # fail-safe: advisory only, never break a cycle
