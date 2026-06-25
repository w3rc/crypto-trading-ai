import { app, BrowserWindow, ipcMain } from "electron";
import { join } from "path";
import { is } from "@electron-toolkit/utils";
import { readSnapshot, dataDir } from "../lib/snapshot";

function createWindow(): void {
  const win = new BrowserWindow({
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

  win.on("ready-to-show", () => win.show());

  if (is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    win.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    win.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(() => {
  ipcMain.handle("snapshot", () => readSnapshot(dataDir()));
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
