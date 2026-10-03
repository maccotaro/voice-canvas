// STEP 3 新しい声: 変換したテイクを並べて聴き比べ、選んだテイクを仕上げて書き出す。
import { useEffect, useRef, useState } from 'react';
import { Sparkles, Loader2, Download, Share2, Check } from 'lucide-react';
import { useCanvaStore, type Take } from '@/stores/canvaStore';
import { encodeSliders } from '@/lib/voice';
import type { Axis } from '@/types/canva';
import { StepHead, WavePlayer, fmtSec } from './parts';

const C = '#fb7185';
const FIN = '#fb923c';
const TAKE_COLORS = ['#7c5cff', '#27e0c4', '#e879f9', '#60a5fa', '#f2b84b', '#34d399'];

// 1つ前のテイクから変えたところ（例「温かさ 70 → 85」）
function diffText(t: Take, prev: Take | undefined, axes: Axis[]) {
  if (!prev) return '最初の設定';
  const ch = axes
    .filter((a) => Math.round(t.sliders[a.key] ?? 50) !== Math.round(prev.sliders[a.key] ?? 50))
    .map((a) => `${a.label} ${Math.round(prev.sliders[a.key] ?? 50)} → ${Math.round(t.sliders[a.key] ?? 50)}`);
  if (ch.length === 0) return '同じ設定でもう一度';
  return ch.length <= 2 ? ch.join('、') : `${ch.slice(0, 2).join('、')} ほか${ch.length - 2}つ`;
}

function Fin({ label, value, display, min, max, step, onChange, disabled }: {
  label: string; value: number; display: string; min: number; max: number; step: number;
  onChange: (v: number) => void; disabled: boolean;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <label className="flex flex-col gap-1 text-xs text-[#b9bedb]">
      <span>{label} <span className="font-mono text-white">{display}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))} aria-label={label}
        style={{
          ['--fill' as string]: FIN,
          background: `linear-gradient(to right, ${FIN} 0%, ${FIN} ${pct}%, #2a2f4d ${pct}%, #2a2f4d 100%)`,
        }} />
    </label>
  );
}

export default function TakesPanel() {
  const {
    axes, takes, currentTake, selectTake, generating, genStartedAt, genError, adv, setAdv, applyAdv, downloadTake,
  } = useCanvaStore();
  const cur = takes.find((t) => t.id === currentTake) ?? null;
  const has = takes.length > 0;

  // 変換中の経過時間
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!generating) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [generating]);

  // 仕上げは選んでいるテイクに少し待ってから掛け直す（再変換しない）
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onAdv = (p: Partial<typeof adv>) => {
    setAdv(p);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void applyAdv(), 350);
  };

  const [copied, setCopied] = useState(false);
  const onShare = async () => {
    if (!cur) return;
    const url = `${window.location.origin}${window.location.pathname}?s=${encodeSliders(cur.sliders, axes)}`;
    try { await navigator.clipboard.writeText(url); } catch { window.prompt('共有リンク', url); }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const tag: [string, string] = generating ? ['作成中', '#e879f9'] : cur ? [`テイク${cur.no}`, C] : ['まだなし', '#9aa0c0'];

  return (
    <section className="bg-panel border border-line rounded-[20px] p-5 flex flex-col gap-3 min-w-0">
      <StepHead n={3} title="新しい声" color={C} Icon={Sparkles} tag={tag[0]} tagColor={tag[1]} empty={!has && !generating} />

      {genError && (
        <div className="text-sm text-[#ff8aa3] bg-[rgba(255,92,124,0.1)] border border-[rgba(255,92,124,0.3)] rounded-xl p-2.5">{genError}</div>
      )}

      {generating && (
        <div className="flex flex-col gap-2.5 p-3.5 rounded-2xl border-2 border-accent" style={{ background: 'linear-gradient(135deg, #2a1f55, #1b2a44)' }}>
          <div className="flex items-center gap-2.5">
            <Loader2 size={20} className="animate-spin text-[#e879f9]" />
            <strong className="font-extrabold">テイク{(takes[0]?.no ?? 0) + 1}</strong>
            <span className="ml-auto font-mono text-[13px] text-[#d6d9ef] tabular-nums">{fmtSec(genStartedAt ? (now - genStartedAt) / 1000 : 0)}</span>
          </div>
          <div className="h-2.5 rounded-full bg-line overflow-hidden">
            <div className="h-full w-1/3 rounded-full animate-[slide_1.6s_ease-in-out_infinite]"
              style={{ background: 'linear-gradient(90deg, #27e0c4, #7c5cff, #e879f9)' }} />
          </div>
        </div>
      )}

      {!has && !generating && (
        <div aria-label="まだテイクはありません" className="flex flex-col gap-2.5">
          {[1, 0.6, 0.3].map((o) => (
            <div key={o} className="h-16 rounded-2xl border-2 border-dashed border-line flex items-center gap-2.5 px-3" style={{ opacity: o }}>
              <span className="w-10 h-10 rounded-full bg-panel2" /><span className="flex-1 h-2.5 rounded-full bg-panel2" />
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2 overflow-y-auto max-h-[460px] pr-0.5">
        {takes.map((t, i) => {
          const on = t.id === currentTake;
          const color = TAKE_COLORS[(t.no - 1) % TAKE_COLORS.length];
          return (
            <div key={t.id} onClick={() => selectTake(t.id)} role="button" aria-pressed={on}
              className="flex flex-col gap-1 px-3 py-2.5 rounded-2xl cursor-pointer transition"
              style={on ? { background: '#221f45', border: '2px solid #7c5cff' } : { background: '#1b1f36', border: '1px solid #2a2f4d' }}>
              <span className="font-bold text-sm">テイク{t.no}{on ? '（選択中）' : ''}</span>
              <WavePlayer src={t.wav} color={color} onPlay={() => selectTake(t.id)}
                label={<span className="text-[#b9bedb]">{diffText(t, takes[i + 1], axes)}</span>} />
            </div>
          );
        })}
      </div>

      {cur?.credit && (
        <p className="text-xs text-sub">元の音声は「{cur.credit}」の読み上げです。使うときはクレジット表記が必要です。</p>
      )}

      <div className="mt-auto flex flex-col gap-3 pt-3.5 border-t border-line" style={{ opacity: cur ? 1 : 0.45 }}>
        <span className="font-extrabold" style={{ color: FIN }}>仕上げて書き出す</span>
        <div className="grid grid-cols-2 gap-5">
          <Fin label="話すスピード" value={adv.speed} display={`${adv.speed.toFixed(2)}x`} min={0.5} max={2} step={0.05}
            onChange={(v) => onAdv({ speed: v })} disabled={!cur} />
          <Fin label="ピッチの揺らぎ" value={adv.pitchVar} display={`${Math.round(adv.pitchVar)}%`} min={0} max={100} step={1}
            onChange={(v) => onAdv({ pitchVar: v })} disabled={!cur} />
        </div>
        <div className="flex gap-2">
          <button onClick={downloadTake} disabled={!cur}
            className="flex-1 min-h-[44px] rounded-xl bg-accent text-white font-bold inline-flex items-center justify-center gap-2 hover:brightness-110 disabled:opacity-50">
            <Download size={16} />WAVを保存
          </button>
          <button onClick={onShare} disabled={!cur} className="btn min-h-[44px] px-4 rounded-xl">
            {copied ? <><Check size={15} className="text-accent2" />コピー済み</> : <><Share2 size={15} />共有リンク</>}
          </button>
        </div>
      </div>
    </section>
  );
}
