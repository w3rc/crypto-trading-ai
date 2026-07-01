import { useEffect, useState } from "react";

type ExchangeId = "hyperliquid" | "binance";
type ExchangeConfigView = {
  activeExchange: ExchangeId;
  testnet: boolean;
  binance: { apiKey: boolean; secret: boolean };
  hyperliquid: { walletAddress: boolean; privateKey: boolean };
};

const api = (window as unknown as { api: {
  getExchangeConfig: () => Promise<ExchangeConfigView>;
  setExchangeConfig: (u: unknown) => Promise<ExchangeConfigView>;
} }).api;

const FIELDS: Record<ExchangeId, { key: string; label: string }[]> = {
  hyperliquid: [
    { key: "walletAddress", label: "Wallet address" },
    { key: "privateKey", label: "Private key (agent wallet)" },
  ],
  binance: [
    { key: "apiKey", label: "API key" },
    { key: "secret", label: "API secret" },
  ],
};

export default function ExchangeSettings(): React.JSX.Element {
  const [view, setView] = useState<ExchangeConfigView | null>(null);
  const [exchange, setExchange] = useState<ExchangeId>("hyperliquid");
  const [testnet, setTestnet] = useState(true);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.getExchangeConfig().then((v) => {
      setView(v); setExchange(v.activeExchange); setTestnet(v.testnet);
    });
  }, []);

  const isSet = (key: string): boolean =>
    !!(view && (view[exchange] as Record<string, boolean>)[key]);

  const save = async (): Promise<void> => {
    const creds: Record<string, string> = {};
    for (const f of FIELDS[exchange]) {
      const val = inputs[f.key];
      if (val && val.length > 0) creds[f.key] = val;   // blank keeps the stored value
    }
    try {
      const v = await api.setExchangeConfig({ activeExchange: exchange, testnet, [exchange]: creds });
      setView(v); setInputs({}); setMsg("Saved.");
    } catch (err) {
      setMsg(`Could not save: ${String(err)}`);
    }
  };

  return (
    <section className="settings-group">
      <div className="settings-group-title">Exchange</div>

      <label className="field-row">
        <span className="field-label">Exchange</span>
        <select className="rail-select" value={exchange}
                onChange={(e) => { setExchange(e.target.value as ExchangeId); setInputs({}); setMsg(""); }}>
          <option value="hyperliquid">Hyperliquid</option>
          <option value="binance">Binance</option>
        </select>
      </label>

      {FIELDS[exchange].map((f) => (
        <label className="field-row" key={f.key}>
          <span className="field-label">{f.label}</span>
          <input type="password" className="cred-input" autoComplete="off"
                 placeholder={isSet(f.key) ? "•••••••• saved" : "not set"}
                 value={inputs[f.key] ?? ""}
                 onChange={(e) => setInputs((s) => ({ ...s, [f.key]: e.target.value }))} />
        </label>
      ))}

      {exchange === "hyperliquid" && (
        <div className="settings-summary cred-note">
          Use a Hyperliquid <b>agent wallet</b> private key — it can trade but not withdraw. Never paste your main wallet key.
        </div>
      )}

      <label className="switch-row" style={{ marginTop: 10 }}>
        <span className="switch">
          <input type="checkbox" checked={testnet} onChange={(e) => setTestnet(e.target.checked)} />
          <span className="switch-slider" />
        </span>
        <span className="switch-label">
          <span className="switch-name">Testnet</span>
          <span className="switch-help">Route shadow/live to the exchange testnet. Turn off for mainnet (real funds).</span>
        </span>
      </label>

      <div className="settings-actions">
        <button className="bt-run" onClick={save}>Save exchange</button>
      </div>
      <div className="settings-summary">Credentials are encrypted on this device and never leave it in plain text. Leave a field blank to keep the saved value.</div>
      {msg && <div className="bt-result">{msg}</div>}
    </section>
  );
}
