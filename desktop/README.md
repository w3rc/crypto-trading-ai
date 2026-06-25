# Crypto Bot Dashboard (Electron)

Read-only Electron desktop app for the paper-trading engine. The main process
reads the engine's `data/{state.json,trades.csv,decisions.jsonl}`; the renderer
polls it over IPC every 5s and draws the equity curve, open positions, and the
per-cycle decision log. It never writes or trades.

## Run (dev)
```bash
cd desktop
npm install
npm run dev
```
Reads `../data` by default. Override with `DATA_DIR=/abs/path npm run dev`.
Keep the bot's cron running and the window updates on its own.

## Build
```bash
npm run build       # bundles main + preload + renderer into out/
npm run start       # preview the built app
```
Packaging to an installer (electron-builder: AppImage / dmg / exe) is a
follow-up; when packaged, set `DATA_DIR` so the app can find the engine's data
dir.

## Test (pure parse/read layer)
```bash
npm test            # vitest — parse.ts + snapshot.ts
```

## Architecture
- **main** (`src/main`) — Node side, the only filesystem touchpoint; reads the
  `data/` files via `src/lib/snapshot.ts` and answers `ipcMain.handle("snapshot")`.
- **preload** (`src/preload`) — `contextBridge` exposes exactly one function,
  `window.api.getSnapshot()`; `contextIsolation` stays on.
- **renderer** (`src/renderer`) — React + Recharts UI; imports only *types* from
  `src/lib/parse.ts`, gets data only via IPC. Dark/glass theme in `index.css`.
