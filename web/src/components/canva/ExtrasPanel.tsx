// そのほかの機能（閉じておく）: 元の音声から特徴を読む／アンカーに登録・まとめて変換・設定のメモリ。
import { useState } from 'react';
import { ChevronDown, ChevronRight, ScanSearch, UserPlus, Save, RotateCcw } from 'lucide-react';
import { useCanvaStore } from '@/stores/canvaStore';
import { canvaApi } from '@/lib/api/canvaApi';
import BatchConvert from './BatchConvert';

export default function ExtrasPanel() {
  const { source, setSliders, memory, saveMemoryPreset, recallMemory } = useCanvaStore();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [memName, setMemName] = useState('');
  const [recallSel, setRecallSel] = useState('');

  const run = async (key: string, fn: () => Promise<string>) => {
    setBusy(key); setMsg(null);
    try { setMsg(await fn()); } catch (e) { setMsg(`できませんでした: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(null); }
  };

  return (
    <section className="bg-panel border border-line rounded-[20px] px-5 py-3">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-1.5 py-1 text-sm text-sub hover:text-white transition">
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}そのほかの機能
      </button>
      {open && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-3 mb-2">
          <div className="bg-panel2 border border-line rounded-xl p-3 space-y-2">
            <div className="text-sm font-bold">元の音声を使う</div>
            <div className="flex gap-2 flex-wrap">
              <button className="btn" disabled={!source || busy != null}
                onClick={() => run('analyze', async () => {
                  const r = await canvaApi.analyze(source!.b64); setSliders(r.sliders);
                  return '元の音声の特徴をスライダーに読み込みました';
                })}><ScanSearch size={14} />特徴をスライダーに読む</button>
              <button className="btn" disabled={!source || busy != null}
                onClick={() => run('add', async () => {
                  // アンカー管理と同じ確認に送る（8秒未満・話し声なしは不採用。品質が低めなら注意つきで採用）
                  await canvaApi.upload(source!.b64, `${source!.label}.wav`);
                  return '確認を始めました。数分かかります。結果はアンカー管理の「素材を追加」に出ます';
                })}><UserPlus size={14} />アンカーに登録</button>
            </div>
            {msg && <p className="text-xs text-sub">{msg}</p>}
          </div>
          <BatchConvert />
          <div className="bg-panel2 border border-line rounded-xl p-3 space-y-2">
            <div className="text-sm font-bold">メモリ（このブラウザに保存）</div>
            <div className="flex gap-2">
              <input value={memName} onChange={(e) => setMemName(e.target.value)} placeholder="名前"
                className="flex-1 bg-bg border border-line rounded px-2 py-1 text-sm" />
              <button onClick={() => saveMemoryPreset(memName)} className="btn"><Save size={14} />記憶</button>
            </div>
            <div className="flex gap-2">
              <select value={recallSel} onChange={(e) => setRecallSel(e.target.value)}
                className="flex-1 bg-bg border border-line rounded px-2 py-1 text-sm">
                <option value="">記憶した設定…</option>
                {memory.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
              <button onClick={() => recallSel && recallMemory(recallSel)} className="btn"><RotateCcw size={14} />呼び出し</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
