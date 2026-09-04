import { useEffect, useRef } from "react";

export type UsIndex = {
  symbol: string;
  name: string;
  last: number;
  day_pct: number;
  line: { t: number; v: number }[];
  freshness: string;
};

export default function UsIndexStrip({
  indexes,
  note,
  onSelect,
}: {
  indexes: UsIndex[];
  note?: string;
  onSelect?: (symbol: string) => void;
}) {
  return (
    <div className="us-block">
      <div className="us-row">
        {indexes.map((ix) => (
          <UsCard key={ix.symbol} ix={ix} onSelect={onSelect} />
        ))}
      </div>
      {note && <p className="tape-note">{note} · tap an index for full chart</p>}
    </div>
  );
}

function UsCard({
  ix,
  onSelect,
}: {
  ix: UsIndex;
  onSelect?: (symbol: string) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const up = ix.day_pct >= 0;
  useEffect(() => {
    const c = ref.current;
    if (!c || !ix.line.length) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const w = c.width;
    const h = c.height;
    const vals = ix.line.map((p) => p.v);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    vals.forEach((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 4) - 2;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = up ? "#5dcea0" : "#ff6b5a";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }, [ix, up]);

  return (
    <button
      type="button"
      className="us-card clickable"
      onClick={() => onSelect?.(ix.symbol)}
      title={`Open ${ix.name} chart`}
    >
      <div className="us-head">
        <strong>{ix.name}</strong>
        <span className={`fresh ${ix.freshness}`}>{ix.freshness}</span>
      </div>
      <div className="us-px">
        {ix.last.toLocaleString("en-US", { maximumFractionDigits: 0 })}
        <span className={up ? "up" : "down"}>
          {up ? "+" : ""}
          {ix.day_pct.toFixed(1)}%
        </span>
      </div>
      <canvas ref={ref} width={160} height={36} />
    </button>
  );
}
