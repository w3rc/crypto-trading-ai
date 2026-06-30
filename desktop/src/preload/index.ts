import { contextBridge, ipcRenderer } from "electron";

const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
  runBacktest: (opts: { since: string; until?: string }) => ipcRenderer.invoke("run-backtest", opts),
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("api", api);
  } catch (error) {
    console.error(error);
  }
}
