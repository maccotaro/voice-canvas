// 録音: マイクで録ってトレイへ（WAV・非圧縮）。
import { useEffect, useRef, useState } from 'react';
import { Mic } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { WavRecorder } from '@/lib/wavRecorder';
import { decodeMono, toWavDataUri, MAX_SEC } from '@/lib/audioTools';
import { ToolHead, ANCHOR_MIN_SEC, toolOf, fmt } from './common';

const C = toolOf('record').color;

export default function RecordTool() {
  const add = useToolsStore((s) => s.add);
  const rec = useRef<WavRecorder | null>(null);
  const [on, setOn] = useState(false);
  const [sec, setSec] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!on) return;
    const t0 = Date.now();
    const id = setInterval(() => setSec((Date.now() - t0) / 1000), 200);
    return () => clearInterval(id);
  }, [on]);
  useEffect(() => () => rec.current?.dispose(), []);

  const start = async () => {
    setError(null); setDone(false);
    try {
      rec.current = new WavRecorder();
      await rec.current.start();
      setSec(0);
      setOn(true);
    } catch (e) {
      setError(`マイクを使えません（ブラウザでマイクを許可してください）: ${e}`);
    }
  };
  const stop = async () => {
    setOn(false);
    try {
      const blob = await rec.current?.stop();
      rec.current = null;
      if (!blob) return;
      const d = await decodeMono(blob);   // 44.1kHz モノラルにそろえる
      const t = new Date();
      add({ name: `録音 ${t.getMonth() + 1}-${t.getDate()} ${t.getHours()}:${String(t.getMinutes()).padStart(2, '0')}`,
        b64: await toWavDataUri(d.data), sec: d.sec, color: C, trail: ['録音'], state: 'ready' });
      setDone(true);
    } catch (e) {
      setError(`録音を確定できませんでした: ${e}`);
    }
  };
  useEffect(() => { if (on && sec >= MAX_SEC) void stop(); }); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <ToolHead k="record" />
      <div className="flex flex-col items-center justify-center gap-3 py-12 rounded-[18px] border-2 transition"
        style={on ? { borderColor: C, background: `${C}0d` } : { borderColor: '#2a2f4d', borderStyle: 'dashed' }}>
        <button onClick={on ? stop : start} aria-label={on ? '録音を止めてトレイへ' : '録音を始める'}
          className="w-24 h-24 rounded-full grid place-items-center transition hover:brightness-110"
          style={{ background: C, boxShadow: on ? `0 0 0 10px ${C}33, 0 0 0 20px ${C}14` : 'none' }}>
          {on ? <span className="w-8 h-8 rounded-md bg-white" /> : <Mic size={40} className="text-bg" />}
        </button>
        <span className="font-mono text-2xl tabular-nums">{fmt(sec)}</span>
        <span className="text-sm" style={{ color: on && sec >= ANCHOR_MIN_SEC ? '#34d399' : '#b9bedb' }}>
          {on ? (sec >= ANCHOR_MIN_SEC ? '止めるとトレイに入ります' : `アンカーに使うなら、あと${Math.ceil(ANCHOR_MIN_SEC - sec)}秒`) : '押して話す（先頭3分まで）'}
        </span>
      </div>
      {error && <p className="text-sm text-[#ff8aa3]">{error}</p>}
      {done && <p className="text-sm text-[#34d399]">トレイに入れました</p>}
    </>
  );
}
