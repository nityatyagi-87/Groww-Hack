import { useState, type FormEvent } from "react";
import { login, setSession, setUserId } from "../lib/api";

export default function Login({ onDone }: { onDone: (name: string) => void }) {
  const [email, setEmail] = useState("arya@signallist.app");
  const [password, setPassword] = useState("paper-only");
  const [name, setName] = useState("Arya");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const res = await login(email, password, name);
      setSession(res.token, res.user_id, res.name);
      setUserId(res.user_id);
      onDone(res.name);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <p className="login-eyebrow">SignalList</p>
        <h1 className="login-title">
          See what changed.
          <em> Then paper-test it.</em>
        </h1>
        <p className="login-sub">
          Server-side last-seen · alt overlays · verified social — not forum tips.
        </p>
        <form onSubmit={submit} className="login-form">
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {err && <p className="login-err">{err}</p>}
          <button type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Enter watchlist"}
          </button>
        </form>
        <p className="login-hint">Demo accepts any credentials · state keyed by email hash</p>
      </div>
    </div>
  );
}
