// Placeholder main process — replaced in Task 4 with the IPC version.
import { app, BrowserWindow } from "electron";
import { join } from "path";

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1200,
    height: 820,
    backgroundColor: "#0a0e1a",
    webPreferences: { preload: join(__dirname, "../preload/index.js"), sandbox: false },
  });
  if (process.env["ELECTRON_RENDERER_URL"]) {
    win.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    win.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
