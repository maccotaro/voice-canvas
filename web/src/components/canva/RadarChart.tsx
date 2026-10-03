// 声の特徴レーダーチャート（軸数可変・SVG）。頂点ドラッグで各軸を編集でき、スライダーと双方向同期。
import { useMemo, useRef } from 'react';
import type { Axis, Sliders } from '@/types/canva';
import { useCanvaStore } from '@/stores/canvaStore';
import { axisMeta } from '@/lib/axisMeta';

export default function RadarChart({ axes, sliders }: { axes: Axis[]; sliders: Sliders }) {
  const setSlider = useCanvaStore((s) => s.setSlider);
  const size = 360;
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 - 56;
  const n = axes.length;
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<number | null>(null);

  const angleOf = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;

  const pts = useMemo(() => {
    return axes.map((a, i) => {
      const ang = angleOf(i);
      const v = Math.max(0, Math.min(100, sliders[a.key] ?? 50)) / 100;
      return {
        ang,
        x: cx + Math.cos(ang) * R * v,
        y: cy + Math.sin(ang) * R * v,
        lx: cx + Math.cos(ang) * (R + 26),
        ly: cy + Math.sin(ang) * (R + 26),
        label: a.label,
        color: axisMeta(a.key).color,
        val: Math.round(sliders[a.key] ?? 50),
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [axes, sliders, n, cx, cy, R]);

  // ポインタ位置(スクリーン)→SVG座標→対象軸の半径方向に射影して 0..100 に変換
  const updateFromEvent = (e: React.PointerEvent) => {
    const i = dragRef.current;
    if (i == null || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * size;
    const py = ((e.clientY - rect.top) / rect.height) * size;
    const ang = angleOf(i);
    const proj = (px - cx) * Math.cos(ang) + (py - cy) * Math.sin(ang); // 軸方向成分
    const v = Math.max(0, Math.min(1, proj / R));
    setSlider(axes[i].key, Math.round(v * 100));
  };

  const onVertexDown = (i: number, e: React.PointerEvent) => {
    e.preventDefault();
    dragRef.current = i;
    svgRef.current?.setPointerCapture(e.pointerId);
    updateFromEvent(e);
  };
  const onMove = (e: React.PointerEvent) => {
    if (dragRef.current != null) updateFromEvent(e);
  };
  const endDrag = (e: React.PointerEvent) => {
    if (dragRef.current == null) return;
    dragRef.current = null;
    try { svgRef.current?.releasePointerCapture(e.pointerId); } catch { /* noop */ }
  };

  const rings = [0.25, 0.5, 0.75, 1];
  const poly = pts.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${size} ${size}`}
      className="w-full max-w-[340px] mx-auto select-none"
      style={{ touchAction: 'none' }}
      onPointerMove={onMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      {rings.map((r, i) => (
        <polygon
          key={i}
          points={axes
            .map((_, j) => {
              const ang = angleOf(j);
              return `${cx + Math.cos(ang) * R * r},${cy + Math.sin(ang) * R * r}`;
            })
            .join(' ')}
          fill="none"
          stroke="#2a2f4d"
          strokeWidth={1}
        />
      ))}
      {pts.map((p, i) => (
        <line key={i} x1={cx} y1={cy} x2={cx + Math.cos(p.ang) * R} y2={cy + Math.sin(p.ang) * R} stroke="#2a2f4d" strokeWidth={1} />
      ))}
      <polygon points={poly} fill="rgba(124,92,255,0.35)" stroke="#a78bfa" strokeWidth={2.5} strokeLinejoin="round" />
      {pts.map((p, i) => (
        <g key={i}>
          {/* 当たり判定を広げる透明円 */}
          <circle
            cx={p.x}
            cy={p.y}
            r={16}
            fill="transparent"
            style={{ cursor: 'grab' }}
            onPointerDown={(e) => onVertexDown(i, e)}
          />
          <circle cx={p.x} cy={p.y} r={6.5} fill={p.color} stroke="#0b0d17" strokeWidth={2} pointerEvents="none" />
        </g>
      ))}
      {pts.map((p, i) => (
        <text key={i} x={p.lx} y={p.ly} fontSize={12} fontWeight={700} fill={p.color} textAnchor="middle" dominantBaseline="middle" pointerEvents="none">
          <tspan x={p.lx} dy="-0.2em">{p.label}</tspan>
          <tspan x={p.lx} dy="1.3em" fill="#c9cdf0" fontSize={11} fontWeight={400}>{p.val}%</tspan>
        </text>
      ))}
    </svg>
  );
}
