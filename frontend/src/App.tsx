import { useEffect, useRef, useState } from "react";
import Login from "./components/Login";
import SymbolDetail from "./components/SymbolDetail";
import UsIndexStrip, { UsIndex } from "./components/UsIndexStrip";
import {
  Digest,
  Quote,
  ackDigest,
  addSymbol,
  clearSession,
  getAltFactors,
  getContext,
  getDigest,
  getDisplayName,
  getHeadlines,
  getPolicy,
  getUniverse,
  getUserId,
  getUsIndexes,
  getWatchlist,
  isLoggedIn,
  liveSocket,
  removeSymbol,
  setSensitivity,
} from "./lib/api";

type SortKey = "symbol" | "day" | "hot";
type ViewTab = "watchlist" | "weather";
type Sens = "low" | "med" | "high";

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [displayName, setDisplayName] = useState(getDisplayName());
  const [digest, setDigest] = useState<Digest | null>(null);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [tape, setTape] = useState<{ label: string; value: string; tone: string }[]>([]);
  const [note, setNote] = useState("");
  const [usIndexes, setUsIndexes] = useState<UsIndex[]>([]);
  const [usNote, setUsNote] = useState("");
  const [factors, setFactors] = useState<
    { label: string; value: number; delta: number; region: string; freshness: string }[]
  >([]);
  const [disruptions, setDisruptions] = useState<
    { kind: string; title: string; region: string; severity: number }[]
  >([]);
  const [headlines, setHeadlines] = useState<
    { id: number; title: string; kind: string; symbols: string[] }[]
  >([]);
  const [universe, setUniverse] = useState<string[]>([]);
  const [pick, setPick] = useState("");
  const [acked, setAcked] = useState(false);
  const [live, setLive] = useState(false);
  const [hot, setHot] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [user, setUser] = useState(getUserId());
  const [policyOpen, setPolicyOpen] = useState(false);
  const [policy, setPolicy] = useState<Record<string, unknown> | null>(null);
  const [sort, setSort] = useState<SortKey>("day");
  const [view, setView] = useState<ViewTab>("watchlist");
  const [search, setSearch] = useState("");
  const [sens, setSens] = useState<Sens>("med");
  const flash = useRef<Record<string, string>>({});
  const prevPx = useRef<Record<string, number>>({});
  const sparks = useRef<Record<string, number[]>>({});
  const [, bump] = useState(0);

  async function loadAll() {
    const [d, w, c, h, u, us, alt] = await Promise.all([
      getDigest(),
      getWatchlist(),
      getContext(),
      getHeadlines(),
      getUniverse(),
      getUsIndexes(),
      getAltFactors(),
    ]);
    setDigest(d);
    setQuotes(w.quotes);
    setTape(c.tape);
    setNote(c.note);
    setHeadlines(h.items);
    setUniverse(u.symbols.filter((s) => !w.symbols.includes(s)));
    setPick(u.symbols.find((s) => !w.symbols.includes(s)) || "");
    setUsIndexes(us.indexes);
    setUsNote(us.note);
    setFactors(Object.values(alt.factors));
    setDisruptions(alt.disruptions);
    setSens((d.sensitivity as Sens) || "med");
    setAcked(false);
  }

  useEffect(() => {
    if (!authed) return;
    loadAll().catch(console.error);
  }, [user, authed]);

  useEffect(() => {
    if (!authed || !digest) return;
    const ws = liveSocket((raw) => {
      const msg = raw as {
        type: string;
        data?: Quote & { symbol?: string; event_type?: string; conflict_delta?: number };
      };
      if (msg.type === "subscribed") setLive(true);
      if (msg.type === "tick" && msg.data?.symbol) {
        const t = msg.data;
        const sym = t.symbol!;
        const old = prevPx.current[sym];
        prevPx.current[sym] = t.price;
        const hist = sparks.current[sym] || [];
        sparks.current[sym] = [...hist.slice(-18), t.price];
        setQuotes((prev) =>
          prev.map((q) =>
            q.symbol === sym
              ? {
                  ...q,
                  price: t.price,
                  day_pct: t.day_pct ?? ((t.price - q.prev_close) / q.prev_close) * 100,
                  volume: t.volume ?? q.volume,
                  ts: t.ts,
                  freshness: t.freshness ?? q.freshness,
                  conflict_delta: t.conflict_delta ?? q.conflict_delta,
                }
              : q
          )
        );
        if (old != null) {
          flash.current[sym] = t.price >= old ? "flash-up" : "flash-down";
          bump((n) => n + 1);
          setTimeout(() => {
            delete flash.current[sym];
            bump((n) => n + 1);
          }, 450);
        }
      }
      if (msg.type === "event" && msg.data?.symbol) {
        setHot((h) => ({ ...h, [msg.data!.symbol!]: msg.data!.event_type || "HOT" }));
      }
    });
    return () => ws.close();
  }, [digest?.items?.length, user, authed]);

  if (!authed) {
    return (
      <Login
        onDone={(name) => {
          setDisplayName(name);
          setUser(getUserId());
          setAuthed(true);
        }}
      />
    );
  }

  async function onAck() {
    if (!digest || acked || digest.items.length === 0) return;
    await ackDigest(digest.items.map((i) => i.id));
    setAcked(true);
    setDigest({ ...digest, items: [], quiet: true });
  }

  async function onSens(level: Sens) {
    setSens(level);
    await setSensitivity(level);
    const d = await getDigest();
    setDigest(d);
    setAcked(false);
  }

  async function onAdd() {
    if (!pick) return;
    try {
      await addSymbol(pick);
      const w = await getWatchlist();
      setQuotes(w.quotes);
      setUniverse((u) => u.filter((s) => s !== pick));
      setPick("");
    } catch (e) {
      alert(String(e));
    }
  }

  async function onRemove(sym: string, e: { stopPropagation: () => void }) {
    e.stopPropagation();
    await removeSymbol(sym);
    setQuotes((q) => q.filter((x) => x.symbol !== sym));
    setUniverse((u) => [...u, sym].sort());
  }

  function logout() {
    clearSession();
    setAuthed(false);
  }

  const away = `${digest?.away_hours.toFixed(1) ?? "—"}h unread window`;
  const selectedQuote = quotes.find((q) => q.symbol === selected);

  const sortedQuotes = [...quotes].sort((a, b) => {
    if (sort === "symbol") return a.symbol.localeCompare(b.symbol);
    if (sort === "hot") return (hot[b.symbol] ? 1 : 0) - (hot[a.symbol] ? 1 : 0);
    return Math.abs(b.day_pct) - Math.abs(a.day_pct);
  });
  const qSearch = search.trim().toUpperCase();
  let visibleQuotes = sortedQuotes;
  if (qSearch) {
    visibleQuotes = visibleQuotes.filter((q) => q.symbol.includes(qSearch));
  }
  const searchHits = qSearch
    ? universe.filter((s) => s.includes(qSearch)).slice(0, 12)
    : [];

  async function openOrAdd(sym: string) {
    const onBook = quotes.some((q) => q.symbol === sym);
    if (!onBook) {
      try {
        await addSymbol(sym);
        const w = await getWatchlist();
        setQuotes(w.quotes);
        setUniverse((u) => u.filter((x) => x !== sym));
      } catch (e) {
        alert(String(e));
        return;
      }
    }
    setSelected(sym);
    setSearch("");
  }

  function fmtTs(ts: number) {
    return new Date(ts * 1000).toLocaleString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      day: "numeric",
      month: "short",
    });
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">
          Signal<span>List</span>
        </h1>
        <div className="meta">
          <div>
            <span className="live-dot" />
            {live ? "Live" : "…"} · {displayName}
          </div>
          <div className="user-row">
            <span className="muted">{away}</span>
            <button
              type="button"
              className="linkish"
              onClick={() =>
                getPolicy().then((p) => {
                  setPolicy(p);
                  setPolicyOpen(true);
                })
              }
            >
              decisions
            </button>
            <button type="button" className="linkish" onClick={logout}>
              logout
            </button>
          </div>
        </div>
      </header>

      <UsIndexStrip indexes={usIndexes} note={usNote} onSelect={(sym) => setSelected(sym)} />
      <div className="tape">
        {tape.map((t) => (
          <div className="tape-item" key={t.label}>
            <span>{t.label}</span>
            <span className={`v ${t.tone}`}>{t.value}</span>
          </div>
        ))}
        {factors.map((f) => (
          <div className="tape-item alt" key={f.label}>
            <span>{f.label.split(" ")[0]}</span>
            <span className="v neu">
              {f.value}
              {f.delta >= 0 ? "↑" : "↓"}
            </span>
            <span className={`fresh ${f.freshness}`}>{f.freshness}</span>
          </div>
        ))}
      </div>
      {note && <p className="tape-note">{note}</p>}
      {disruptions.length > 0 && (
        <div className="lag-banner">
          {disruptions.map((d) => (
            <span key={d.kind}>
              LAG · {d.title} ({d.region})
            </span>
          ))}
        </div>
      )}

      <div className="tf-row lab-filters" style={{ padding: "0 1.25rem" }}>
        <button
          type="button"
          className={view === "watchlist" ? "on" : ""}
          onClick={() => setView("watchlist")}
        >
          Watchlist
        </button>
        <button
          type="button"
          className={view === "weather" ? "on" : ""}
          onClick={() => setView("weather")}
        >
          Weather / crop
        </button>
      </div>

      <main className="main">
        {view === "weather" ? (
          <section>
            <h2 className="section-h">Weather / crop</h2>
            <p className="section-s">
              Single alt overlay — LAG when disruption runs ahead of price (Param 1/6).
            </p>
            <div className="digest-list">
              {factors.map((f) => (
                <article className="digest-card" key={f.label}>
                  <span className={`badge LAG_ALERT`}>WEATHER</span>
                  <div>
                    <p className="card-title">{f.label}</p>
                    <p className="card-sub">
                      {f.region} · {f.value} ({f.delta >= 0 ? "+" : ""}
                      {f.delta})
                    </p>
                  </div>
                  <span className={`fresh ${f.freshness}`}>{f.freshness}</span>
                </article>
              ))}
              {disruptions.map((d) => (
                <article className="digest-card" key={d.kind}>
                  <span className="badge LAG_ALERT">LAG ALERT</span>
                  <div>
                    <p className="card-title">{d.title}</p>
                    <p className="card-sub">
                      {d.region} · severity {d.severity.toFixed(2)}
                    </p>
                  </div>
                </article>
              ))}
              {factors.length === 0 && <p className="muted">No weather factor yet.</p>}
            </div>
          </section>
        ) : (
          <>
            <section>
              <h2 className="section-h">Since you left</h2>
              <p className="section-s">
                Event taxonomy = meaningful change:{" "}
                {(digest?.taxonomy || []).join(" · ") ||
                  "MICRO_SPIKE · SESSION_MOVE · OPEN_GAP · CATALYST · LAG_ALERT · QUIET"}
              </p>
              <div className="sens-row">
                <span className="muted">Sensitivity</span>
                {(["low", "med", "high"] as Sens[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={sens === s ? "on" : ""}
                    onClick={() => onSens(s)}
                  >
                    {s}
                  </button>
                ))}
                <span className="muted">
                  floor {digest?.threshold_floor?.toFixed(0) ?? "—"}
                </span>
              </div>
              <div className="digest-list">
                {digest?.quiet && digest.quiet_card && (
                  <article className="digest-card">
                    <span className="badge QUIET">{digest.quiet_card.event_type}</span>
                    <div>
                      <p className="card-title">
                        {digest.quiet_card.symbol} · {digest.quiet_card.magnitude}
                      </p>
                      <p className="card-sub">{digest.quiet_card.reason}</p>
                      <p className="card-meta">{fmtTs(digest.quiet_card.ts)}</p>
                    </div>
                    <span className={`fresh ${digest.quiet_card.freshness}`}>
                      {digest.quiet_card.freshness}
                    </span>
                  </article>
                )}
                {digest?.items.map((item, i) => (
                  <article
                    className="digest-card clickable"
                    key={item.id}
                    style={{ animationDelay: `${i * 0.04}s` }}
                    onClick={() => setSelected(item.symbol)}
                  >
                    <span className={`badge ${item.event_type}`}>
                      {item.event_type.replace("_", " ")}
                    </span>
                    <div>
                      <p className="card-title">
                        {item.symbol} · {item.magnitude}
                        {item.count > 1 ? ` · ×${item.count}` : ""}
                      </p>
                      <p className="card-sub">{item.reason}</p>
                      <p className="card-meta">
                        {fmtTs(item.ts)} ·{" "}
                        <span className={`peer ${item.peer}`}>{item.peer}</span>
                      </p>
                    </div>
                    <span className={`fresh ${item.freshness}`}>{item.freshness}</span>
                  </article>
                ))}
              </div>
              {digest && digest.items.length > 0 && (
                <button className={`ack ${acked ? "done" : ""}`} onClick={onAck} disabled={acked}>
                  {acked ? "Marked read" : "Mark unread seen"}
                </button>
              )}
            </section>

            <section>
              <h2 className="section-h">Live book</h2>
              <p className="section-s">Search · add · freshness (incl. CONFLICT) · open chart.</p>
              <div className="tf-row lab-filters">
                {(["day", "hot", "symbol"] as SortKey[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={sort === s ? "on" : ""}
                    onClick={() => setSort(s)}
                  >
                    sort:{s}
                  </button>
                ))}
              </div>
              <div className="grid-wrap">
                <div className="grid-head">
                  <span>Symbol</span>
                  <span>Spark</span>
                  <span>Price</span>
                  <span>Day %</span>
                  <span>Fresh</span>
                  <span />
                </div>
                {visibleQuotes.map((q) => {
                  const up = q.day_pct >= 0;
                  return (
                    <div
                      key={q.symbol}
                      className={`grid-row clickable ${flash.current[q.symbol] || ""}`}
                      onClick={() => setSelected(q.symbol)}
                    >
                      <span className="sym">
                        {q.symbol} {hot[q.symbol] && <span className="hot">{hot[q.symbol]}</span>}
                      </span>
                      <MiniSpark values={sparks.current[q.symbol] || [q.price]} up={up} />
                      <span>{q.price?.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                      <span className={up ? "up" : "down"}>
                        {up ? "+" : ""}
                        {q.day_pct?.toFixed(2)}%
                      </span>
                      <span className={`fresh ${q.freshness || "LIVE"}`}>
                        {q.freshness || "LIVE"}
                        {q.freshness === "CONFLICT" && q.conflict_delta != null
                          ? ` ${q.conflict_delta}bp`
                          : ""}
                      </span>
                      <button
                        type="button"
                        className="linkish"
                        onClick={(e) => onRemove(q.symbol, e)}
                      >
                        remove
                      </button>
                    </div>
                  );
                })}
              </div>
              <div className="manage search-bar">
                <input
                  className="search-input"
                  placeholder="Search stocks · misc · gold · US indexes…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {searchHits.length > 0 && (
                  <div className="search-hits">
                    {searchHits.map((s) => (
                      <button key={s} type="button" onClick={() => openOrAdd(s)}>
                        {s} · chart
                      </button>
                    ))}
                  </div>
                )}
                {qSearch && visibleQuotes.length === 0 && searchHits.length === 0 && (
                  <p className="tf-label">No match for “{search}”</p>
                )}
              </div>
              <div className="manage">
                <select value={pick} onChange={(e) => setPick(e.target.value)}>
                  <option value="">Add symbol…</option>
                  {universe.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <button type="button" onClick={onAdd}>
                  Add
                </button>
              </div>
            </section>
          </>
        )}
      </main>

      <footer className="strip strip-slow">
        <div className="strip-track">
          {[...headlines, ...headlines].map((h, i) => (
            <span className="strip-item" key={`${h.id}-${i}`}>
              <span className="k">{h.kind}</span>
              {h.title}
              <span className="s">{h.symbols.join(" · ")}</span>
            </span>
          ))}
        </div>
      </footer>

      {selected && (
        <SymbolDetail
          symbol={selected}
          onClose={() => setSelected(null)}
          livePrice={selectedQuote?.price}
          dayPct={selectedQuote?.day_pct}
          freshness={selectedQuote?.freshness}
        />
      )}

      {policyOpen && policy && (
        <div className="detail-overlay" onClick={() => setPolicyOpen(false)}>
          <div className="detail-panel policy" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="back" onClick={() => setPolicyOpen(false)}>
              ← Close
            </button>
            <h2 className="detail-sym">Product decisions</h2>
            <pre className="policy-pre">{JSON.stringify(policy, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

function MiniSpark({ values, up }: { values: number[]; up: boolean }) {
  const pts = values.length > 1 ? values : [values[0] || 0, values[0] || 0];
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const w = 56;
  const h = 22;
  const d = pts
    .map((v, i) => {
      const x = (i / (pts.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 2) - 1;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="mini-spark" aria-hidden>
      <path d={d} fill="none" stroke={up ? "#5dcea0" : "#ff6b5a"} strokeWidth="1.5" />
    </svg>
  );
}
