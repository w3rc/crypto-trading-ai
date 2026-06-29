# Dashboard Liveness — design

**Status:** proposed 2026-06-29
**Branch:** new `feat/dashboard-liveness` off `main` (7c6d878).
**Source:** prod-readiness audit findings A1 (Critical), A2, A3 (Important) — `.superpowers/sdd/prod-readiness-audit.md`.

## Goal

Make the dashboard honest about whether the bot is **alive, fresh, and thinking** — the audit's #1 felt gap. Today a stopped cron looks identical to a healthy bot, and one failure mode (LLM fallback) buries the decision log. Three pieces:

1. **Freshness / "bot stopped"** — show data age; flag STALE when the bot likely stopped.
2. **Brain health** — show when the LLM brain is in fallback (degraded) vs thinking.
3. **Decision-log collapse** — stop identical repeated reasons from burying the log.

## Decisions (locked unless vetoed)

### A1 — Freshness, cadence-aware (one small engine touch)
The engine is a one-shot run by an **external cron**, so neither side knows the cadence today. Rather than guess a fixed threshold (wrong for any owner whose cron ≠ the guess), the owner declares it once:

- **Engine:** add optional `interval_seconds` to `config.yaml` (the owner sets it to match their cron; **default 900** = 15 min). `_status_payload` writes it into `status.json` as `interval_seconds`.
- **Dashboard:** a pure helper `freshness(status, nowMs) -> { ageSec, label, stale }` in `status.ts`:
  - age from `status.ts` (ISO) vs `nowMs`; `label` = `"updated 8s ago"` / `"4m ago"` / `"2h ago"`.
  - `stale = ageSec > 2.5 × interval` (interval from status, **fallback 900** if absent).
  - The existing **5 s poll** already re-runs every render, so age keeps growing against `Date.now()` even when the file is static → a stopped bot crosses the threshold and flips to STALE on its own. No extra timer.
- **Sidebar:** a freshness line under the mode badge — `"updated 8s ago"` normally; when `stale`, a distinct **`STALE · updated Xm ago`** treatment (a stopped bot). When `status` is entirely absent → `"no data · is the bot running?"`.

### A2 — Brain health, client-side derive (no engine change)
The engine already encodes the signal: a degraded cycle writes `reason = "llm-fallback: …"` (`engine/llm.py:74-75`). The dashboard derives it:

- `brainHealth(decisions) -> { state: "ok" | "degraded" | "unknown", since?: n }` in `status.ts`: look at the most recent decisions; if the latest reason `startsWith("llm-fallback:")` → `degraded` (+ count of the trailing run of fallbacks); else `ok`; empty → `unknown`.
- **Sidebar:** a small **`Brain: OK` / `Brain: DEGRADED`** chip. Degraded uses the same amber/`--down` cue family.
- *Ponytail:* derived from decisions, not a new status field — zero engine risk. `# ponytail: client-derived brain health; promote to a status.brain field if decisions.jsonl ever lags.`

### A3 — Decision-log collapse (pure dashboard)
- `DecisionLog` collapses **consecutive identical `reason`** rows into one row carrying a `×N` count (newest timestamp shown). Executed trades and any distinct reason always stay their own row — collapse only merges adjacent duplicates.
- Long reasons truncate (~80 chars) with the full text on `title=` hover.
- Net effect: 16 identical credential errors → one `… ×16` row; the real signal (executed trades, genuine holds) stays visible.

## Files
- `engine/config.py` — `interval_seconds` (default 900) on `Config` + `load_config`.
- `engine/bot.py` — `_status_payload` writes `interval_seconds`.
- `engine/config.yaml` — documented `interval_seconds:` line.
- `desktop/src/lib/parse.ts` — `Status` gains `interval_seconds?: number`.
- `desktop/src/lib/status.ts` — `freshness(...)`, `brainHealth(...)` helpers (unit-tested).
- `desktop/src/renderer/src/components/Sidebar.tsx` — freshness line + brain chip.
- `desktop/src/renderer/src/components/DecisionLog.tsx` — consecutive-duplicate collapse.
- `desktop/src/renderer/src/index.css` — `.stale` / brain-chip styles.

## Safety / scope
- No change to the live-trading safety model, the toggle, or `create_order`. `interval_seconds` is display-only metadata; it never gates trading.
- `interval_seconds` is optional everywhere (backward-compatible with old `status.json`).

## Testing
- **vitest (`src/lib`):** `freshness` (fresh→label+!stale; just-past-2.5×→stale; missing status→absent; missing interval→900 fallback); `brainHealth` (latest fallback→degraded+count; latest ok→ok; empty→unknown).
- **pytest:** `interval_seconds` defaults to 900 and is overridden from yaml; `_status_payload` carries it.
- **build:** `npm run build` exit 0.
- **Playwright (controller, 1280/768/375):** fresh bot → "updated Xs ago" + Brain OK; stale `status.ts` → `STALE · updated Xm ago`; degraded decisions → Brain DEGRADED + collapsed `×N` row; missing status → "no data" line.

## Out of scope (later batches)
Packaged data-dir fix (C1), single-instance (C2), `.env` autoload + sentiment-in-all-modes + cron (B-track), CI (C9). This batch is liveness only.
