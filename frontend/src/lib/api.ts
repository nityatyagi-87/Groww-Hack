const USER_KEY = "signallist_user";
const TOKEN_KEY = "signallist_token";
const NAME_KEY = "signallist_name";

/** Production: set VITE_API_URL=https://your-api.onrender.com (no trailing slash). Local: leave empty (Vite proxy). */
const API_BASE = String(import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function wsBase(): string {
  if (API_BASE) {
    const u = new URL(API_BASE);
    return `${u.protocol === "https:" ? "wss" : "ws"}://${u.host}`;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}`;
}

export function getUserId(): string {
  return localStorage.getItem(USER_KEY) || "demo";
}

export function setUserId(id: string) {
  localStorage.setItem(USER_KEY, id.trim() || "demo");
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getDisplayName(): string {
  return localStorage.getItem(NAME_KEY) || "Trader";
}

export function setSession(token: string, userId: string, name: string) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, userId);
  localStorage.setItem(NAME_KEY, name);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(NAME_KEY);
}

export function isLoggedIn(): boolean {
  return Boolean(localStorage.getItem(TOKEN_KEY));
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-User-Id": getUserId(),
    ...(init?.headers as Record<string, string> | undefined),
  };
  const tok = getToken();
  if (tok) headers.Authorization = `Bearer ${tok}`;
  const res = await fetch(apiUrl(path), { ...init, headers });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Param 2 — digest card + peer flag */
export type DigestItem = {
  id: number;
  symbol: string;
  event_type: string;
  magnitude: string;
  reason: string;
  ts: number;
  freshness: string;
  peer: "IDIOSYNCRATIC" | "SECTOR" | string;
  count: number;
  rank: number;
};

export type Digest = {
  user_id: string;
  sensitivity: string;
  threshold_floor: number;
  away_hours: number;
  taxonomy: string[];
  corroboration_model: string;
  items: DigestItem[];
  quiet: boolean;
  quiet_card: {
    symbol: string;
    event_type: string;
    magnitude: string;
    reason: string;
    ts: number;
    freshness: string;
    peer?: string;
    count?: number;
  } | null;
};

export type Quote = {
  symbol: string;
  price: number;
  prev_close: number;
  day_pct: number;
  volume: number;
  ts: number;
  freshness?: string;
  age_s?: number;
  source?: string;
  conflict_delta?: number;
};

export type ChartData = {
  symbol: string;
  tf: string;
  label: string;
  last: number;
  change_pct: number;
  candles: { t: number; o: number; h: number; l: number; c: number; v: number }[];
  line: { t: number; v: number }[];
  timeframes: string[];
  overlays?: { id: string; label: string; unit: string; points: { t: number; v: number }[] }[];
  exposure?: { sectors: string[]; overlays: string[] };
};

export const getDigest = () => api<Digest>("/api/digest");
export const ackDigest = (eventIds: number[]) =>
  api<{ ok: boolean; marked: number }>("/api/digest/ack", {
    method: "POST",
    body: JSON.stringify({ event_ids: eventIds }),
  });
export const getSensitivity = () =>
  api<{ sensitivity: string; threshold_mult: number }>("/api/sensitivity");
export const setSensitivity = (sensitivity: "low" | "med" | "high") =>
  api<{ sensitivity: string }>("/api/sensitivity", {
    method: "PUT",
    body: JSON.stringify({ sensitivity }),
  });
export const getWatchlist = () =>
  api<{ symbols: string[]; quotes: Quote[]; max_watchlist?: number }>("/api/watchlist");
export const addSymbol = (symbol: string) =>
  api<{ symbols: string[] }>("/api/watchlist", {
    method: "POST",
    body: JSON.stringify({ symbol }),
  });
export const removeSymbol = (symbol: string) =>
  api<{ symbols: string[] }>(`/api/watchlist/${symbol}`, { method: "DELETE" });
export const getContext = () =>
  api<{
    tape: { label: string; value: string; tone: string }[];
    note: string;
    regime: string;
  }>("/api/context");
export const getHeadlines = () =>
  api<{
    items: {
      id: number;
      title: string;
      source: string;
      kind: string;
      symbols: string[];
      ts: number;
    }[];
  }>("/api/headlines");
export const getUniverse = () => api<{ symbols: string[] }>("/api/universe");
export const getChart = (symbol: string, tf: string) =>
  api<ChartData>(`/api/chart/${symbol}?tf=${tf}`);
export const getSymbolEvents = (symbol: string) =>
  api<{ items: { id: number; event_type: string; score: number; ts: number }[] }>(
    `/api/symbol/${symbol}/events`
  );
export const getPolicy = () => api<Record<string, unknown>>("/api/policy");
export const getUsIndexes = () =>
  api<{
    indexes: {
      symbol: string;
      name: string;
      last: number;
      day_pct: number;
      line: { t: number; v: number }[];
      freshness: string;
    }[];
    note: string;
  }>("/api/alt/us-indexes");
export const getAltFactors = () =>
  api<{
    factors: Record<
      string,
      { label: string; value: number; delta: number; region: string; freshness: string }
    >;
    disruptions: { kind: string; title: string; region: string; severity: number }[];
  }>("/api/alt/factors");

export const login = (email: string, password: string, name?: string) =>
  api<{ token: string; user_id: string; name: string; email: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });

export function liveSocket(onMsg: (data: unknown) => void): WebSocket {
  const ws = new WebSocket(
    `${wsBase()}/ws/live?user=${encodeURIComponent(getUserId())}`
  );
  ws.onmessage = (e) => onMsg(JSON.parse(e.data));
  const iv = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 20000);
  ws.onclose = () => clearInterval(iv);
  return ws;
}
