import { contextBridge, ipcRenderer } from "electron";

const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
  runBacktest: (opts: { since: string; until?: string }) => ipcRenderer.invoke("run-backtest", opts),
  runBot: () => ipcRenderer.invoke("run-bot"),
  getSchedule: () => ipcRenderer.invoke("get-schedule"),
  setSchedule: (s: { enabled: boolean; intervalSeconds: number }) => ipcRenderer.invoke("set-schedule", s),
  setSymbols: (list: string[]) => ipcRenderer.invoke("set-symbols", list),
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("api", api);
  } catch (error) {
    console.error(error);
  }
}
