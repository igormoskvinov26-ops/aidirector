import { useEffect, useState } from "react";

/** Шкала «минус — плюс» с тонкой стрелкой. value в тех же единицах, что и span. */
export default function Gauge({
  value, span, label, text, minus, plus, tick,
}: { value: number; span: number; label: string; text: string; minus: string; plus: string; tick: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => { const t = setTimeout(() => setShown(value), 50); return () => clearTimeout(t); }, [value]);
  const k = Math.max(-1, Math.min(1, shown / span));
  const R = 120, C = 150;
  const pt = (f: number, r = R) => {
    const a = Math.PI * (1 - (f + 1) / 2);
    return [C + r * Math.cos(a), C - r * Math.sin(a)];
  };
  const arc = (f1: number, f2: number) => {
    const [x1, y1] = pt(f1), [x2, y2] = pt(f2);
    return `M${x1} ${y1} A${R} ${R} 0 0 1 ${x2} ${y2}`;
  };
  const seg = 24;
  const col = value >= 0 ? plus : minus;
  return (
    <svg viewBox="-25 -12 350 217" className="w-full max-h-[165px]" role="img" aria-label={`${label}: ${text}`}>
      {Array.from({ length: seg }, (_, i) => {
        const f1 = -1 + (2 * i) / seg, f2 = -1 + (2 * (i + 1)) / seg;
        const mid = (f1 + f2) / 2;
        return (
          <path key={i} d={arc(f1 + 0.008, f2 - 0.008)} fill="none" strokeWidth={10}
            stroke={mid < 0 ? minus : plus} strokeOpacity={0.2 + 0.8 * Math.abs(mid)} />
        );
      })}
      {Array.from({ length: 21 }, (_, i) => {
        const f = -1 + i / 10;
        const big = i % 5 === 0;
        const [x1, y1] = pt(f, R + 10), [x2, y2] = pt(f, R + (big ? 20 : 15));
        return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={tick} strokeWidth={big ? 1.5 : 0.8} />;
      })}
      {[-1, 0, 1].map((f) => {
        const [tx, ty] = pt(f, R + 32);
        return (
          <text key={f} x={tx} y={ty + 4} textAnchor="middle" fontSize={10} fill={tick}>
            {f === 0 ? "0" : `${f > 0 ? "+" : "−"}${span}%`}
          </text>
        );
      })}
      <g style={{ transform: `rotate(${k * 90}deg)`, transformOrigin: `${C}px ${C}px`, transition: "transform 1.2s cubic-bezier(.2,1.4,.4,1)" }}>
        <polygon points={`${C - 2.5},${C} ${C + 2.5},${C} ${C},${C - R + 4}`} fill={col} />
      </g>
      <circle cx={C} cy={C} r={8} fill={col} />
      <circle cx={C} cy={C} r={3} fill="#fff" fillOpacity={0.8} />
      <text x={C} y={C + 32} textAnchor="middle" fontSize={24} fontWeight={600} fill={col}>{text}</text>
      <text x={C} y={C + 47} textAnchor="middle" fontSize={9} fill={tick} letterSpacing={2}>{label}</text>
    </svg>
  );
}
