import { contextBridge, ipcRenderer } from "electron";

const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("api", api);
  } catch (error) {
    console.error(error);
  }
}
