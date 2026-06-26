import base64
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


# ---- CryptoPanic (news) — per-coin, uses native bullish/bearish votes ----

def cryptopanic(symbols, cfg, backtest=False, ts_ms=None):
    if backtest:
        return {}
    token = os.environ.get("CRYPTOPANIC_TOKEN", "")
    if not token:
        return {}
    out = {}
    for sym in symbols:
        try:
            url = ("https://cryptopanic.com/api/v1/posts/?public=true&auth_token="
                   + urllib.parse.quote(token) + "&currencies=" + _coin(sym))
            data = _http_json(url, timeout=cfg.sentiment.http_timeout)
            pos = neg = 0
            for post in data.get("results", []):
                v = post.get("votes", {})
                pos += v.get("positive", 0)
                neg += v.get("negative", 0)
            total = pos + neg
            if total:
                out[sym] = _clamp((pos - neg) / total)
        except Exception:
            continue
    return out


# ---- Reddit (social) — OAuth client-credentials, VADER over titles ----

def _reddit_token(cfg):
    cid = os.environ.get("REDDIT_CLIENT_ID", "")
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not (cid and secret):
        return None
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=body,
        headers={"Authorization": f"Basic {auth}",
                 "User-Agent": "cryptotrading-bot/1.0"})
    with urllib.request.urlopen(req, timeout=cfg.sentiment.http_timeout) as resp:
        return json.loads(resp.read().decode()).get("access_token")


def reddit(symbols, cfg, backtest=False, ts_ms=None):
    if backtest:
        return {}
    try:
        token = _reddit_token(cfg)
    except Exception:
        token = None
    if not token:
        return {}
    headers = {"Authorization": f"bearer {token}",
               "User-Agent": "cryptotrading-bot/1.0"}
    out = {}
    for sym in symbols:
        try:
            url = ("https://oauth.reddit.com/r/CryptoCurrency/search?restrict_sr=1"
                   "&limit=25&sort=new&q=" + urllib.parse.quote(_coin(sym)))
            data = _http_json(url, headers=headers, timeout=cfg.sentiment.http_timeout)
            titles = [c.get("data", {}).get("title", "")
                      for c in data.get("data", {}).get("children", [])]
            score = _vader_score(titles)
            if score is not None:
                out[sym] = _clamp(score)
        except Exception:
            continue
    return out


# ---- X / Twitter (social) — bearer token, VADER over recent tweets ----

def x_twitter(symbols, cfg, backtest=False, ts_ms=None):
    if backtest:
        return {}
    token = os.environ.get("X_BEARER_TOKEN", "")
    if not token:
        return {}
    headers = {"Authorization": f"Bearer {token}",
               "User-Agent": "cryptotrading-bot/1.0"}
    out = {}
    for sym in symbols:
        try:
            q = urllib.parse.quote(f"{_coin(sym)} crypto -is:retweet lang:en")
            url = ("https://api.twitter.com/2/tweets/search/recent?max_results=25"
                   "&query=" + q)
            data = _http_json(url, headers=headers, timeout=cfg.sentiment.http_timeout)
            texts = [t.get("text", "") for t in data.get("data", [])]
            score = _vader_score(texts)
            if score is not None:
                out[sym] = _clamp(score)
        except Exception:
            continue
    return out


SOURCES = {"fear_greed": fear_greed, "cryptopanic": cryptopanic,
           "reddit": reddit, "x_twitter": x_twitter}
