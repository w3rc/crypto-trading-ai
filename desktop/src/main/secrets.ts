import { app, safeStorage } from "electron";
import { existsSync, readFileSync, writeFileSync } from "fs";
import { join } from "path";
import {
  DEFAULT_CREDS, redact, mergeUpdate, envForActive,
  ExchangeCreds, ExchangeConfigView, ExchangeConfigUpdate,
} from "../lib/exchange-creds";

function credsPath(): string {
  return join(app.getPath("userData"), "exchange-creds.enc");
}

// Decrypt the stored blob, or fall back to defaults (missing file, unavailable keychain,
// or a corrupt/undecryptable blob) — reads must never throw.
function load(): ExchangeCreds {
  try {
    const p = credsPath();
    if (!existsSync(p) || !safeStorage.isEncryptionAvailable()) return DEFAULT_CREDS;
    const json = safeStorage.decryptString(readFileSync(p));
    return { ...DEFAULT_CREDS, ...JSON.parse(json) } as ExchangeCreds;
  } catch {
    return DEFAULT_CREDS;
  }
}

export function getExchangeConfig(): ExchangeConfigView {
  return redact(load());
}

export function setExchangeConfig(update: ExchangeConfigUpdate): ExchangeConfigView {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("secure storage unavailable — your OS keychain isn't accessible, so keys can't be stored safely");
  }
  const next = mergeUpdate(load(), update);
  writeFileSync(credsPath(), safeStorage.encryptString(JSON.stringify(next)));
  return redact(next);
}

export function exchangeEnv(): Record<string, string> {
  return envForActive(load());
}
