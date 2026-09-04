import { useEffect, useRef, useState } from "react";
import { ChartData, getChart, getSymbolEvents } from "../lib/api";

const TFS = ["1D", "1W", "1M", "3M", "1Y"] as const;
type Mode = "line" | "candle";
const OV_COLORS = ["#7eb6ff", "#f0c35a", "#c9a0ff", "#5dcea0", "#ff8f7a"];

type Props = {
  symbol: string;
  onClose: () => void;
  livePrice?: number;
  dayPct?: number;
  freshness?: string;
};

export default function SymbolDetail({
  symbol,
  onClose,
  livePrice,
  dayPct,
  freshness,
}: Props) {
  const [tf, setTf] = useState<(typeof TFS)[number]>("1D");
  const [mode, setMode] = useState<Mode>("candle");
  const [data, setData] = useState<ChartData | null>(null);
  const [events, setEvents] = useState<
    { id: number; event_type: string; score: number; ts: number }[]
  >([]);
  const [hover, setHover] = useState<{ t: number; o?: number; h?: number; l?: number; c: number } | null>(
    null
  );
  const [showAlt, setShowAlt] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [c, e] = await Promise.all([getChart(symbol, tf), getSymbolEvents(symbol)]);
      if (cancelled) return;
      setData(c);
      setEvents(e.items);
    })().catch(console.error);
    return () => {
      cancelled = true;
    };
  }, [symbol, tf]);

  useEffect(() => {
    if (!data || !canvasRef.current) return;
    drawChart(canvasRef.current, data, mode, showAlt, setHover);
  }, [data, mode, showAlt]);

  const last = livePrice ?? data?.last ?? 0;
  const ch = data?.change_pct ?? dayPct ?? 0;
  const up = ch >= 0;
  const overlays = data?.overlays || [];

  return (
    <div className="detail-overlay" onClick={onClose} role="presentation">
      <div
        className="detail-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`${symbol} chart`}
      >
        <div className="detail-top">
          <div>
            <button className="back" onClick={onClose} type="button">
              ← Watchlist
            </button>
            <h2 className="detail-sym">{symbol}</h2>
            <div className="detail-price">
              <span>{last.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
              <span className={up ? "up" : "down"}>
                {up ? "+" : ""}
                {ch.toFixed(2)}%
              </span>
              {freshness && <span className={`fresh ${freshness}`}>{freshness}</span>}
            </div>
            {data?.exposure && (
              <p className="tf-label">
                Exposure: {data.exposure.sectors.join(" · ")} — overlays{" "}
                {data.exposure.overlays.join(", ")}
              </p>
            )}
          </div>
          <div className="mode-tog">
            <button type="button" className={mode === "line" ? "on" : ""} onClick={() => setMode("line")}>
              Line
            </button>
            <button
              type="button"
              className={mode === "candle" ? "on" : ""}
              onClick={() => setMode("candle")}
            >
              Candle
            </button>
            {overlays.length > 0 && (
              <button
                type="button"
                className={showAlt ? "on" : ""}
                onClick={() => setShowAlt((v) => !v)}
              >
                Weather/crop
              </button>
            )}
          </div>
        </div>

        <div className="tf-row">
          {TFS.map((t) => (
            <button key={t} type="button" className={tf === t ? "on" : ""} onClick={() => setTf(t)}>
              {t}
            </button>
          ))}
        </div>
        <p className="tf-label">{data?.label || "Loading…"}</p>

        <div className="chart-box">
          <canvas ref={canvasRef} width={720} height={280} />
          {hover && (
            <div className="chart-tip">
              {new Date(hover.t * 1000).toLocaleString("en-IN", {
                month: "short",
                day: "numeric",
                hour: tf === "1D" ? "2-digit" : undefined,
                minute: tf === "1D" ? "2-digit" : undefined,
              })}
              {mode === "candle" && hover.o != null
                ? ` · O ${hover.o} H ${hover.h} L ${hover.l} C ${hover.c}`
                : ` · ${hover.c}`}
            </div>
          )}
        </div>

        {showAlt && overlays.length > 0 && (
          <div className="ov-legend">
            {overlays.map((o, i) => (
              <span key={o.id} style={{ color: OV_COLORS[i % OV_COLORS.length] }}>
                ▬ {o.label}
              </span>
            ))}
          </div>
        )}

        <div className="detail-events">
          <h3>Signals on {symbol}</h3>
          {events.length === 0 && <p className="empty">No recent events</p>}
          {events.map((ev) => (
            <div key={ev.id} className="ev-row">
              <span className={`badge ${ev.event_type}`}>{ev.event_type.replace("_", " ")}</span>
              <span className="muted">
                {new Date(ev.ts * 1000).toLocaleString("en-IN", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className="score-sm">{ev.score.toFixed(0)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function drawChart(
  canvas: HTMLCanvasElement,
  data: ChartData,
  mode: Mode,
  showAlt: boolean,
  onHover: (h: { t: number; o?: number; h?: number; l?: number; c: number } | null) => void
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 720;
  const cssH = 280;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const pad = { t: 16, r: 52, b: 28, l: 12 };
  const w = cssW - pad.l - pad.r;
  const h = cssH - pad.t - pad.b;
  const candles = data.candles;
  if (!candles.length) return;

  let min = Math.min(...candles.map((c) => c.l));
  let max = Math.max(...candles.map((c) => c.h));
  const padPx = (max - min) * 0.06 || 1;
  min -= padPx;
  max += padPx;

  const xAt = (i: number) => pad.l + (i / Math.max(candles.length - 1, 1)) * w;
  const yAt = (v: number) => pad.t + ((max - v) / (max - min)) * h;

  ctx.clearRect(0, 0, cssW, cssH);
  ctx.strokeStyle = "rgba(180,220,190,0.1)";
  for (let g = 0; g < 4; g++) {
    const y = pad.t + (h * g) / 3;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
    ctx.fillStyle = "#8aa394";
    ctx.font = "11px DM Sans, sans-serif";
    ctx.fillText((max - ((max - min) * g) / 3).toFixed(0), pad.l + w + 6, y + 4);
  }

  const upColor = "#5dcea0";
  const downColor = "#ff6b5a";

  if (mode === "line") {
    ctx.beginPath();
    candles.forEach((c, i) => {
      const x = xAt(i);
      const y = yAt(c.c);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = data.change_pct >= 0 ? upColor : downColor;
    ctx.lineWidth = 2;
    ctx.stroke();
  } else {
    const bw = Math.max(2, (w / candles.length) * 0.55);
    candles.forEach((c, i) => {
      const x = xAt(i);
      const bull = c.c >= c.o;
      ctx.strokeStyle = bull ? upColor : downColor;
      ctx.fillStyle = bull ? upColor : downColor;
      ctx.beginPath();
      ctx.moveTo(x, yAt(c.h));
      ctx.lineTo(x, yAt(c.l));
      ctx.stroke();
      const y1 = yAt(Math.max(c.o, c.c));
      const y2 = yAt(Math.min(c.o, c.c));
      ctx.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
    });
  }

  // Alt overlays — normalize each series into chart band (top 35%)
  if (showAlt && data.overlays?.length) {
    data.overlays.forEach((ov, oi) => {
      const pts = ov.points;
      if (pts.length < 2) return;
      const vals = pts.map((p) => p.v);
      const omin = Math.min(...vals);
      const omax = Math.max(...vals);
      const ospan = omax - omin || 1;
      const bandTop = pad.t;
      const bandH = h * 0.35;
      ctx.beginPath();
      pts.forEach((p, i) => {
        const idx = Math.round((i / (pts.length - 1)) * (candles.length - 1));
        const x = xAt(idx);
        const y = bandTop + bandH - ((p.v - omin) / ospan) * bandH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = OV_COLORS[oi % OV_COLORS.length];
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    });
  }

  ctx.fillStyle = "#8aa394";
  ctx.font = "11px DM Sans, sans-serif";
  [0, Math.floor(candles.length / 2), candles.length - 1].forEach((i) => {
    const label = new Date(candles[i].t * 1000).toLocaleDateString("en-IN", {
      month: "short",
      day: "numeric",
    });
    ctx.fillText(label, xAt(i) - 18, cssH - 8);
  });

  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const i = Math.round(((mx - pad.l) / w) * (candles.length - 1));
    if (i < 0 || i >= candles.length) return onHover(null);
    const c = candles[i];
    onHover({ t: c.t, o: c.o, h: c.h, l: c.l, c: c.c });
  };
  canvas.onmouseleave = () => onHover(null);
}
