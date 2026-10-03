// ピッチ: 高さ（半音）とテンポを変える（soundtouchjs）。試聴してからトレイへ。
import { useEffect, useRef, useState } from 'react';
import { Loader2, AlertTriangle, Play } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { decodeDataUri, pitchShift, toWavDataUri, secOf } from '@/lib/audioTools';
import { WavePlayer } from '@/components/canva/parts';
import { ToolHead, InputPick, Primary, toolOf } from './common';

const C = toolOf('pitch').color;

function Big({ label, value, unit, min, max, step, v, onChange, ticks }: {
  label: string; value: string; unit: string; min: number; max: number; step: number; v: number;
  onChange: (v: number) => void; ticks: [string, string, string];
}) {
  const pct = ((v - min) / (max - min)) * 100;
  return (
    <div className="flex flex-col gap-2.5 p-4 rounded-[18px] bg-panel2 border border-line">
      <div className="flex items-baseline gap-2">
        <span className="font-extrabold">{label}</span>
        <span className="ml-auto font-mono text-[28px]" style={{ color: C }}>{value}</span>
        <span className="text-xs text-[#b9bedb]">{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => onChange(Number(e.target.value))} aria-label={label}
        style={{ ['--fill' as string]: C, background: `linear-gradient(to right, ${C} 0%, ${C} ${pct}%, #2a2f4d ${pct}%, #2a2f4d 100%)` }} />
      <div className="flex justify-between text-[11px] text-sub"><span>{ticks[0]}</span><span>{ticks[1]}</span><span>{ticks[2]}</span></div>
    </div>
  );
}

export default function PitchTool() {
  const { clips, inputId, add } = useToolsStore();
  const input = clips.find((c) => c.id === inputId && c.state === 'ready');
  const [semi, setSemi] = useState(0);
  const [tempo, setTempo] = useState(1);
  const [preview, setPreview] = useState<{ b64: string; sec: number; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const src = useRef<{ id: string; data: Float32Array } | null>(null);

  useEffect(() => { setPreview(null); setDone(false); }, [input?.id]);
  const key = `${input?.id}:${semi}:${tempo}`;

  const render = async () => {
    if (!input) return null;
    if (preview?.key === key) return preview;
    setBusy(true);
    try {
      if (src.current?.id !== input.id) src.current = { id: input.id, data: await decodeDataUri(input.b64) };
      const out = pitchShift(src.current.data, semi, tempo);
      const p = { b64: await toWavDataUri(out), sec: secOf(out), key };
      setPreview(p);
      return p;
    } finally {
      setBusy(false);
    }
  };

  const toTray = async () => {
    const p = await render();
    if (!p || !input) return;
    const tag = `${semi > 0 ? '+' : ''}${semi}半音${tempo !== 1 ? `・${tempo.toFixed(2)}倍` : ''}`;
    add({ name: `${input.name}（${tag}）`, b64: p.b64, sec: p.sec, color: C, trail: [...input.trail, 'ピッチ'], state: 'ready' });
    setDone(true);
  };

  const fresh = preview?.key === key;
  return (
    <>
      <ToolHead k="pitch" />
      <InputPick clip={input} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Big label="高さ" value={`${semi > 0 ? '+' : ''}${semi}`} unit="半音" min={-12} max={12} step={1} v={semi}
          onChange={(v) => { setSemi(v); setDone(false); }} ticks={['−12（1オクターブ下）', '0', '+12']} />
        <Big label="テンポ" value={tempo.toFixed(2)} unit="倍" min={0.5} max={2} step={0.05} v={tempo}
          onChange={(v) => { setTempo(v); setDone(false); }} ticks={['0.5（ゆっくり）', '1.0', '2.0']} />
      </div>
      <div className="flex items-center gap-3 p-3.5 rounded-2xl" style={{ background: '#1d1a3a', border: `2px solid ${fresh ? C : `${C}55`}` }}>
        {fresh ? <div className="flex-1"><WavePlayer src={preview!.b64} color={C} /></div> : (
          <button onClick={() => void render()} disabled={!input || busy} className="btn">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} style={{ color: C }} />}この設定で試聴する
          </button>
        )}
      </div>
      <div className="flex items-center gap-2 text-xs text-[#f2d58b]">
        <AlertTriangle size={15} className="text-[#f2b84b] shrink-0" />
        高さを変えた声をアンカーにすると、元の人とは違う声の材料になります
      </div>
      {done && <p className="text-sm text-[#34d399]">トレイに入れました</p>}
      <div className="mt-auto flex flex-wrap gap-2.5">
        <Primary color={C} disabled={!input || busy} onClick={() => void toTray()}>
          {busy && <Loader2 size={18} className="animate-spin" />}この高さでトレイへ
        </Primary>
        <button className="btn min-h-[52px] px-5 rounded-[14px]" onClick={() => { setSemi(0); setTempo(1); }}>元に戻す</button>
      </div>
    </>
  );
}
