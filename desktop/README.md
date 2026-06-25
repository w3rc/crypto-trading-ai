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
## Package (distributable)
```bash
npm run dist        # installer into dist/ (Linux AppImage · mac dmg · win nsis)
npm run dist:dir    # faster: unpacked app in dist/linux-unpacked/ (no installer)
```
A packaged build can't assume the repo layout, so point it at the engine's data
dir via `DATA_DIR`:
```bash
DATA_DIR=/abs/path/to/cryptotrading_ai/data ./dist/linux-unpacked/crypto-bot-desktop
```
Config lives in `electron-builder.yml`. A custom app icon under `build/` is an
optional follow-up (the default Electron icon is used otherwise).

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
