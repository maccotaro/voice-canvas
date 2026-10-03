// 3列の作業台で使う小さな部品: 列の見出し・実波形・再生ボタン付きの波形。
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Play, Pause, type LucideIcon } from 'lucide-react';

// 列の見出し（STEP n ＋ 題名 ＋ 状態タグ）。未完了は点線の枠で「まだ空」を見せる
export function StepHead({ n, title, color, Icon, tag, tagColor, empty, children }: {
  n: number; title: string; color: string; Icon: LucideIcon;
  tag: string; tagColor: string; empty?: boolean; children?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <span
        className="w-12 h-12 shrink-0 rounded-[14px] grid place-items-center"
        style={empty ? { border: `2px dashed ${color}`, color } : { background: color, color: '#0b0d17' }}
      >
        <Icon size={24} />
      </span>
      <div className="leading-tight">
        <div className="text-[11px] font-mono" style={{ color }}>STEP {n}</div>
        <h2 className="text-xl font-extrabold whitespace-nowrap">{title}</h2>
      </div>
      <span className={`ml-auto text-[11px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${children ? 'hidden sm:inline' : ''}`}
        style={{ color: tagColor, background: `${tagColor}22` }}>{tag}</span>
      {children}
    </div>
  );
}

// 列と列のあいだの矢印。前の列が埋まると色がつく
export function FlowArrow({ active, color }: { active: boolean; color: string }) {
  const c = active ? color : '#3a3f63';
  return (
    <div aria-hidden className="hidden lg:grid absolute -right-[25px] top-7 w-[30px] h-[30px] rounded-full bg-bg place-items-center z-10"
      style={{ border: `2px solid ${c}` }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
    </div>
  );
}

// data URI の音声から波形の山（0..1）と長さを取り出す
const cache = new Map<string, { peaks: number[]; sec: number }>();
export function usePeaks(b64: string | null, n = 48) {
  const [res, setRes] = useState<{ peaks: number[]; sec: number } | null>(null);
  useEffect(() => {
    if (!b64) { setRes(null); return; }
    const key = `${n}:${b64.length}:${b64.slice(-64)}`;
    const hit = cache.get(key);
    if (hit) { setRes(hit); return; }
    let alive = true;
    (async () => {
      try {
        const buf = await (await fetch(b64)).arrayBuffer();
        const ctx = new AudioContext();
        const ab = await ctx.decodeAudioData(buf).finally(() => ctx.close());
        const ch = ab.getChannelData(0);
        const step = Math.max(1, Math.floor(ch.length / n));
        const raw = Array.from({ length: n }, (_, i) => {
          let m = 0;
          for (let j = i * step; j < Math.min(ch.length, (i + 1) * step); j++) m = Math.max(m, Math.abs(ch[j]));
          return m;
        });
        const top = Math.max(...raw, 1e-6);
        const out = { peaks: raw.map((v) => 0.12 + 0.88 * (v / top)), sec: ab.duration };
        cache.set(key, out);
        if (alive) setRes(out);
      } catch {
        if (alive) setRes(null);
      }
    })();
    return () => { alive = false; };
  }, [b64, n]);
  return res;
}

export const fmtSec = (t: number) =>
  `${Math.floor(t / 60)}:${Math.floor(t % 60).toString().padStart(2, '0')}`;

export function Bars({ peaks, color, progress = 1, height = 30 }: {
  peaks: number[]; color: string; progress?: number; height?: number;
}) {
  return (
    <div className="flex-1 flex items-center gap-[2px]" style={{ height }}>
      {peaks.map((h, i) => (
        <div key={i} className="flex-1 rounded-full"
          style={{ height: `${Math.round(h * 100)}%`, background: i / peaks.length <= progress ? color : '#3a3f63' }} />
      ))}
    </div>
  );
}

// 再生ボタン＋実波形。再生中は再生位置まで色を塗る
export function WavePlayer({ src, color, label, onPlay }: {
  src: string; color: string; label?: ReactNode; onPlay?: () => void;
}) {
  const p = usePeaks(src);
  const ref = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  useEffect(() => { setPlaying(false); setPos(0); }, [src]);
  const toggle = () => {
    const el = ref.current;
    if (!el) return;
    onPlay?.();
    if (el.paused) { void el.play(); setPlaying(true); } else { el.pause(); setPlaying(false); }
  };
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2.5">
        <button onClick={toggle} aria-label={playing ? '止める' : '聴く'}
          className="w-10 h-10 shrink-0 rounded-full grid place-items-center text-bg hover:brightness-110 transition"
          style={{ background: color }}>
          {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" className="ml-0.5" />}
        </button>
        {p ? <Bars peaks={p.peaks} color={color} progress={playing || pos > 0 ? pos : 1} />
          : <div className="flex-1 h-[30px] rounded bg-panel2" />}
      </div>
      <div className="flex justify-between text-xs text-[#d6d9ef]">
        <span className="truncate">{label}</span>
        <span className="font-mono tabular-nums text-sub">{p ? fmtSec(p.sec) : ''}</span>
      </div>
      <audio ref={ref} src={src} className="hidden"
        onTimeUpdate={(e) => { const el = e.currentTarget; if (el.duration) setPos(el.currentTime / el.duration); }}
        onEnded={() => { setPlaying(false); setPos(0); }} />
    </div>
  );
}
