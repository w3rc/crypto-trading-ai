# Sidebar Mode Toggle (paper / shadow / live) — design

**Status:** approved 2026-06-29
**Branch:** rides on `feat/dashboard-redesign` (ships in the same PR as the dashboard redesign).
**Builds on:** the redesign's `Sidebar.tsx` + `modeBadge` helper + the live-execution slice (`mode`, `_live_armed`, `data/HALT`, `_status_payload`).

## Goal

A 3-segment `[ Paper | Shadow | Live ]` toggle at the bottom of the dashboard rail that changes the bot's running mode — **without** weakening the live-trading safety model. The toggle writes a control file the engine reads as a mode override; **live still requires the operator's `LIVE_TRADING_ARMED=yes` env to actually place orders**, so a dashboard click alone can never move real money.

## Safety invariant (the point of the design)

`mode == "live"` only places real orders when `_live_armed()` (env `LIVE_TRADING_ARMED == "yes"`) is also true; otherwise the bot routes to `_run_shadow` and places nothing. This routing is unchanged. The toggle only changes how `mode` gets its value (a control file vs `config.yaml`); it does NOT touch the env gate. **Therefore the toggle setting `live` while unarmed runs shadow — zero real money.** This must be covered by a test.

## Architecture

### Write path (dashboard → engine)
A single narrow write surface — a control file in the existing `data/` dir.

- **lib writer** (`desktop/src/lib/control.ts`): `writeControl(dir, mode)` writes `data/control.json` = `{ "mode": mode }`, but only for `mode in {"paper","shadow","live"}` (throws/rejects otherwise — invalid values can never be written).
- **main IPC** (`desktop/src/main/index.ts`): `ipcMain.handle("set-mode", (_e, mode) => writeControl(dataDir(), mode))`.
- **preload** (`desktop/src/preload/index.ts`): expose `setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode)`.

### Engine override read
- `engine/config.py` `load_config`: after building the config, check `<data_dir>/control.json`. If it exists and holds a valid `mode` (`paper|shadow|live`), that mode **overrides** the config/`mode` value. Missing file, unreadable, bad JSON, or an out-of-set value → ignore, keep the config mode (fail-safe; never raises).
- Net effect: `cfg.mode` reflects the dashboard's choice when present, else `config.yaml`. The existing leverage/credential/etc. logic is unchanged.

### Honest status (`armed`)
Because `mode==live` + unarmed silently runs shadow, the dashboard must show the true state:
- `engine/bot.py` `_status_payload` gains **`armed`** = `_live_armed()` (a top-level bool). Paper/shadow paths pass it too (it is simply false unless the env is set).
- `desktop/src/lib/status.ts` `modeBadge` extends to `modeBadge(mode?, halted?, armed?)`:
  - `halted` → `{label:"HALTED", tone:"halted"}` (overrides everything)
  - `mode==="live"` && `armed` → `{label:"LIVE", tone:"live"}` (solid amber, real money)
  - `mode==="live"` && **!armed** → `{label:"LIVE · UNARMED", tone:"live-unarmed"}` (configured live but running shadow — distinct treatment)
  - `mode==="shadow"` → `{label:"SHADOW", tone:"shadow"}`
  - else → `{label:"PAPER", tone:"paper"}`
- New CSS tone `.mode-live-unarmed` (amber outline / dimmed, visually distinct from solid `.mode-live`).

### Renderer toggle
- A 3-segment control in `Sidebar.tsx` at the **bottom of the rail** (above the footer). Segments: Paper / Shadow / Live.
- **Active segment** = the running mode from `status.mode`. After a click, the component keeps a local `pending` mode and highlights it optimistically with a small **"applies next cycle"** hint until `status.mode` matches (the bot picks up `control.json` on its next run).
- **Paper / Shadow** click → `window.api.setMode(mode)` immediately.
- **Live** click → an **OK/Cancel `window.confirm`** ("Switch bot to LIVE mode? Real orders place only if LIVE_TRADING_ARMED=yes is set in the bot's env.") — only on OK does it call `setMode("live")`.
- The rail status badge already uses `modeBadge`; with the new `armed` arg it shows LIVE vs LIVE · UNARMED correctly.
- Footer "read-only" wording softened (the dashboard now has this one write).

## Components / files

- `engine/config.py` — control.json override read (+ a small helper, e.g. `_mode_override(data_dir)`).
- `engine/bot.py` — `armed` in `_status_payload` (all call sites).
- `desktop/src/lib/control.ts` (new) — `writeControl(dir, mode)` with validation.
- `desktop/src/lib/status.ts` — `modeBadge` gains `armed`; new tone `"live-unarmed"`.
- `desktop/src/main/index.ts` — `set-mode` IPC.
- `desktop/src/preload/index.ts` — `setMode` on the bridge.
- `desktop/src/renderer/src/components/Sidebar.tsx` — the toggle + confirm + optimistic/pending highlight; consumes `setMode` via the existing `window.api`.
- `desktop/src/renderer/src/index.css` — segment-control styles + `.mode-live-unarmed`.
- `desktop/src/lib/parse.ts` — `Status` gains `armed?: boolean`.

## Error handling

- Invalid mode to `writeControl` → rejected (never written). The IPC surfaces only the three valid values from the UI anyway.
- `control.json` missing/corrupt/invalid → engine ignores it, uses config mode (fail-safe).
- `setMode` IPC failure → the toggle keeps showing the actual `status.mode` (no optimistic stick); a transient failure just means the click didn't take — next click retries.
- A torn read of `control.json` (write/read race) → bad JSON → engine fail-safe to config mode for that cycle; corrected next cycle.

## Out of scope

Changing the env arm from the UI (stays operator/terminal-only — the hard money-gate); persisting/scheduling modes; multi-bot control; auth on the IPC (single-user local app).

## Testing

- **Python (pytest):**
  - `load_config` honors `data/control.json` mode override; invalid value → config mode; missing → config mode; corrupt JSON → config mode.
  - `_status_payload` includes `armed` (true when env set, false otherwise).
  - **Safety:** `control.json` mode `live` + env NOT armed ⇒ bot routes to shadow, **no `create_order`**, decisions `executed:false`. (The toggle cannot move money without the env.)
- **vitest (`src/lib`):** `writeControl` writes `{mode}` for valid modes and rejects invalid ones (write a temp dir, assert file contents / that no file is written on invalid). `modeBadge` armed matrix: live+armed→live, live+!armed→live-unarmed, shadow, paper, halted-overrides.
- **Build:** `npm run build` exit 0.
- **Playwright (controller, 1280/768/375):** the toggle renders at the rail bottom; clicking Shadow/Paper switches the active segment; clicking Live shows the confirm; the rail badge shows LIVE (armed) vs LIVE · UNARMED (not armed) vs SHADOW/PAPER, and HALTED overrides. Clean up harness after.
