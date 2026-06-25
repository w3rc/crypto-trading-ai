// Placeholder preload — replaced in Task 4 with the getSnapshot bridge.
import { contextBridge } from "electron";

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("api", {});
  } catch (error) {
    console.error(error);
  }
}
