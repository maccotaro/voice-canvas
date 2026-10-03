// 結合: トレイの音声を順につなぐ（つなぎ目はクロスフェード）。短い録音を集めて 8 秒以上にする、など。
import { useState } from 'react';
import { ArrowUp, ArrowDown, X, Plus, Loader2 } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { decodeDataUri, join, toWavDataUri, secOf } from '@/lib/audioTools';
import { ToolHead, Primary, ANCHOR_MIN_SEC, toolOf } from './common';

const C = toolOf('join').color;

export default function JoinTool() {
  const { clips, handoff, add } = useToolsStore();
  const ready = clips.filter((c) => c.state === 'ready');
  // 「ツールに回す」で来たらその素材を最初に入れておく
  const [ids, setIds] = useState<string[]>(() => (handoff && ready.some((c) => c.id === handoff) ? [handoff] : []));
  const [xf, setXf] = useState(0.2);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const list = ids.map((id) => ready.find((c) => c.id === id)).filter((c): c is NonNullable<typeof c> => !!c);
  const total = Math.max(0, list.reduce((s, c) => s + c.sec, 0) - xf * Math.max(0, list.length - 1));
  const scale = Math.max(total, ANCHOR_MIN_SEC * 1.4);
  const move = (i: number, d: number) => setIds((a) => {
    const b = [...a];
    [b[i], b[i + d]] = [b[i + d], b[i]];
    return b;
  });

  const run = async () => {
    setBusy(true); setDone(false);
    try {
      const parts = await Promise.all(list.map((c) => decodeDataUri(c.b64)));
      const out = join(parts, xf);
      add({ name: `${list[0].name}ほか${list.length - 1}本をつないだもの`, b64: await toWavDataUri(out), sec: secOf(out), color: C,
        trail: ['結合'], state: 'ready' });
      setDone(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ToolHead k="join" />
      <div className="flex flex-col gap-2">
        {list.map((c, i) => (
          <div key={c.id} className="flex items-center gap-2.5 px-3 py-2.5 rounded-2xl bg-panel2 border border-line">
            <span className="w-6 h-6 rounded-full grid place-items-center text-xs font-mono" style={{ background: `${c.color}33`, color: c.color }}>{i + 1}</span>
            <span className="font-bold text-[13px] truncate">{c.name}</span>
            <span className="ml-auto font-mono text-xs text-sub">{c.sec.toFixed(1)}秒</span>
            <button className="btn px-2" disabled={i === 0} onClick={() => move(i, -1)} aria-label="前へ"><ArrowUp size={13} /></button>
            <button className="btn px-2" disabled={i === list.length - 1} onClick={() => move(i, 1)} aria-label="後ろへ"><ArrowDown size={13} /></button>
            <button className="btn px-2" onClick={() => setIds((a) => a.filter((x) => x !== c.id))} aria-label="外す"><X size={13} /></button>
          </div>
        ))}
        <div className="flex gap-2">
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="トレイから足す"
            className="flex-1 min-h-[40px] rounded-xl bg-panel2 border border-dashed border-line px-2.5 text-sm">
            <option value="">トレイから足す…</option>
            {ready.map((c) => <option key={c.id} value={c.id}>{c.name}（{c.sec.toFixed(1)}秒）</option>)}
          </select>
          <button className="btn" disabled={!pick} onClick={() => { setIds((a) => [...a, pick]); setPick(''); setDone(false); }}
            style={{ color: C }}><Plus size={14} />足す</button>
        </div>
      </div>

      <div className="flex flex-col gap-2 p-4 rounded-2xl bg-panel2 border border-line">
        <div className="flex items-baseline gap-2">
          <span className="font-extrabold">つないだ長さ</span>
          <span className="ml-auto font-mono text-xl" style={{ color: total >= ANCHOR_MIN_SEC ? '#34d399' : '#f2b84b' }}>{total.toFixed(1)}秒</span>
        </div>
        <div className="relative">
          <div className="h-[26px] rounded-lg bg-line overflow-hidden flex">
            {list.map((c) => <div key={c.id} className="h-full border-r-2 border-bg" style={{ width: `${(c.sec / scale) * 100}%`, background: c.color }} />)}
          </div>
          <span className="absolute -top-1 bottom-0 w-0.5 bg-[#34d399]" style={{ left: `${(ANCHOR_MIN_SEC / scale) * 100}%` }} />
        </div>
        <span className="text-[11px] text-[#34d399]" style={{ paddingLeft: `calc(${(ANCHOR_MIN_SEC / scale) * 100}% - 40px)` }}>
          {ANCHOR_MIN_SEC}秒（アンカーに使える最低の長さ）
        </span>
        <label className="flex flex-col gap-1 text-xs text-[#b9bedb]">
          <span>つなぎ目のクロスフェード <span className="font-mono text-white">{xf.toFixed(2)}秒</span></span>
          <input type="range" min={0} max={1} step={0.05} value={xf} onChange={(e) => setXf(Number(e.target.value))} aria-label="クロスフェード"
            style={{ ['--fill' as string]: C, background: `linear-gradient(to right, ${C} 0%, ${C} ${xf * 100}%, #2a2f4d ${xf * 100}%, #2a2f4d 100%)` }} />
        </label>
      </div>
      {done && <p className="text-sm text-[#34d399]">トレイに入れました</p>}
      <div className="mt-auto">
        <Primary color={C} disabled={list.length < 2 || busy} onClick={() => void run()}>
          {busy && <Loader2 size={18} className="animate-spin" />}つないでトレイへ
        </Primary>
      </div>
    </>
  );
}
