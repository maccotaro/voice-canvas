// カット: 波形の上で範囲を選び、その範囲だけ残す／その範囲を消す。フェードイン・アウトを付けられる。
import { useEffect, useRef, useState } from 'react';
import WaveSurfer from 'wavesurfer.js';
import RegionsPlugin, { type Region } from 'wavesurfer.js/dist/plugins/regions.esm.js';
import { Play, Square, Loader2 } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { decodeDataUri, slice, removeRange, fade, toWavDataUri, secOf } from '@/lib/audioTools';
import { ToolHead, InputPick, Primary, LengthTag, toolOf } from './common';

const C = toolOf('cut').color;
const fmt1 = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;

export default function CutTool() {
  const { clips, inputId, add } = useToolsStore();
  const input = clips.find((c) => c.id === inputId && c.state === 'ready');
  const box = useRef<HTMLDivElement | null>(null);
  const region = useRef<Region | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [fin, setFin] = useState(0.1);
  const [fout, setFout] = useState(0.2);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    if (!input || !box.current) return;
    setRange(null); setDone(null);
    const regions = RegionsPlugin.create();
    const ws = WaveSurfer.create({
      container: box.current, height: 130, waveColor: `${C}55`, progressColor: `${C}55`, cursorColor: '#e8eaf6',
      barWidth: 3, barGap: 2, barRadius: 2, url: input.b64, plugins: [regions],
    });
    wsRef.current = ws;
    ws.on('decode', (dur) => {
      // 初めは真ん中あたりを 12 秒（短ければ全体）選んでおく
      const len = Math.min(12, dur);
      const start = Math.max(0, dur / 2 - len / 2);
      region.current = regions.addRegion({ start, end: start + len, color: `${C}33`, drag: true, resize: true });
      setRange([start, start + len]);
    });
    regions.enableDragSelection({ color: `${C}33` });
    regions.on('region-created', (r) => {
      // 選び直したら前の範囲を消す（範囲は1つだけ）
      regions.getRegions().forEach((x) => { if (x !== r) x.remove(); });
      region.current = r;
      setRange([r.start, r.end]);
    });
    regions.on('region-updated', (r) => setRange([r.start, r.end]));
    ws.on('pause', () => setPlaying(false));
    ws.on('finish', () => setPlaying(false));
    regions.on('region-out', () => { ws.pause(); setPlaying(false); });
    return () => ws.destroy();
  }, [input?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const playRange = () => {
    const r = region.current;
    if (!r) return;
    if (playing) { wsRef.current?.pause(); setPlaying(false); return; }
    r.play();
    setPlaying(true);
  };

  const run = async (mode: 'keep' | 'remove') => {
    if (!input || !range) return;
    setBusy(true); setDone(null);
    try {
      const data = await decodeDataUri(input.b64);
      const out = mode === 'keep' ? fade(slice(data, range[0], range[1]), fin, fout) : removeRange(data, range[0], range[1]);
      const label = mode === 'keep' ? `${fmt1(range[0])}〜${fmt1(range[1])}` : `${fmt1(range[0])}〜${fmt1(range[1])}を除く`;
      add({ name: `${input.name} ${label}`, b64: await toWavDataUri(out), sec: secOf(out), color: C,
        trail: [...input.trail, 'カット'], state: 'ready' });
      setDone('トレイに入れました');
    } finally {
      setBusy(false);
    }
  };

  const len = range ? range[1] - range[0] : 0;
  return (
    <>
      <ToolHead k="cut" />
      <InputPick clip={input} />
      {input ? (
        <div className="p-3.5 rounded-2xl bg-panel2 border border-line">
          <div ref={box} className="w-full" />
          <p className="text-[11px] text-sub mt-1.5">波形の上をドラッグすると範囲を選び直せます。範囲の端をつまんで広げたり狭めたりできます</p>
        </div>
      ) : <div className="h-[160px] rounded-2xl border-2 border-dashed border-line" />}

      {range && (
        <div className="flex flex-wrap items-center gap-3.5">
          <span className="font-mono text-[15px]">{fmt1(range[0])} 〜 {fmt1(range[1])}</span>
          <LengthTag sec={len} />
          <button className="btn ml-auto" onClick={playRange}>
            {playing ? <Square size={13} /> : <Play size={13} style={{ color: C }} />}選んだ範囲を聴く
          </button>
        </div>
      )}
      <div className="grid grid-cols-2 gap-5">
        {([['フェードイン', fin, setFin], ['フェードアウト', fout, setFout]] as const).map(([label, v, setV]) => (
          <label key={label} className="flex flex-col gap-1 text-xs text-[#b9bedb]">
            <span>{label} <span className="font-mono text-white">{v.toFixed(2)}秒</span></span>
            <input type="range" min={0} max={1} step={0.05} value={v} onChange={(e) => setV(Number(e.target.value))}
              style={{ ['--fill' as string]: C, background: `linear-gradient(to right, ${C} 0%, ${C} ${v * 100}%, #2a2f4d ${v * 100}%, #2a2f4d 100%)` }} />
          </label>
        ))}
      </div>
      {done && <p className="text-sm text-[#34d399]">{done}</p>}

      <div className="mt-auto flex flex-wrap gap-2.5">
        <Primary color={C} disabled={!range || busy} onClick={() => run('keep')}>
          {busy && <Loader2 size={18} className="animate-spin" />}選んだ範囲を残す
        </Primary>
        <button className="btn min-h-[52px] px-5 rounded-[14px]" disabled={!range || busy} onClick={() => run('remove')}>選んだ範囲を消す</button>
      </div>
    </>
  );
}
