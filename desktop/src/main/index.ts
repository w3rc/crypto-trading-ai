import { app, BrowserWindow, ipcMain, shell } from "electron";
import { join } from "path";
import { is } from "@electron-toolkit/utils";
import { readSnapshot, dataDir, readBacktestRun, clearBacktestHistory } from "../lib/snapshot";
import { writeControl, writeAutoExecute, writeStrategy } from "../lib/control";
import { runBacktest, runBot, runSentiment, executeSuggestion } from "./engine";
import { removePending } from "../lib/pending";
import { applySchedule } from "./scheduler";
import { readSchedule, writeSchedule } from "../lib/scheduler";
import { writeSymbols } from "../lib/symbols";

let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 820,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#0a0e1a",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
    },
  });

  mainWindow.on("ready-to-show", () => mainWindow?.show());

  if (is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();                                   // a second launch hands off to the running one
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    ipcMain.handle("snapshot", () => readSnapshot(dataDir()));
    ipcMain.handle("set-mode", (_e, mode: string) => writeControl(dataDir(), mode));
    ipcMain.handle("set-strategy", (_e, name: string) => writeStrategy(dataDir(), name));
    ipcMain.handle("run-backtest", (_e, opts) => runBacktest(opts));
    ipcMain.handle("get-backtest-run", (_e, id: string) => readBacktestRun(dataDir(), id));
    ipcMain.handle("clear-backtest-history", () => clearBacktestHistory(dataDir()));
    ipcMain.handle("run-bot", () => runBot());
    ipcMain.handle("run-sentiment", () => runSentiment());
    ipcMain.handle("get-schedule", () => readSchedule(dataDir()));
    ipcMain.handle("set-schedule", async (_e, s) => {
      const saved = await writeSchedule(dataDir(), s);
      applySchedule(saved);
      return saved;
    });
    ipcMain.handle("set-symbols", (_e, list) => writeSymbols(dataDir(), list));
    ipcMain.handle("execute-suggestion", (_e, sym: string) => executeSuggestion(sym));
    ipcMain.handle("dismiss-suggestion", (_e, sym: string) => removePending(dataDir(), sym));
    ipcMain.handle("set-auto-execute", (_e, on: boolean) => writeAutoExecute(dataDir(), on));
    ipcMain.handle("open-external", (_e, url: string) => {   // https-only: don't shell out arbitrary schemes
      if (typeof url === "string" && url.startsWith("https://")) return shell.openExternal(url);
    });
    readSchedule(dataDir()).then(applySchedule);   // arm the schedule on startup
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
