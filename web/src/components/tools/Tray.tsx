// 素材トレイ: ツールで作った音声の置き場。別のツールに回す・アンカーに追加・元の音声に使う・保存・消す。
import { useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { Inbox, Upload, ArrowRight, UserPlus, AudioLines, Download, X, Loader2, Check } from 'lucide-react';
import { useToolsStore, type Clip } from '@/stores/toolsStore';
import { useCanvaStore } from '@/stores/canvaStore';
import { canvaApi } from '@/lib/api/canvaApi';
import { decodeMono, toWavDataUri } from '@/lib/audioTools';
import { WavePlayer } from '@/components/canva/parts';
import { TOOLS, ANCHOR_MIN_SEC, fmt } from './common';

export default function Tray() {
  const { clips, add, update, remove, setTool } = useToolsStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  // トレイに直接ファイルを置く（音声も動画も。先頭3分まで、モノラルにする）
  const putFiles = async (files: FileList | File[]) => {
    setBusy(true); setError(null);
    for (const f of Array.from(files)) {
      try {
        const d = await decodeMono(f);
        add({ name: f.name.replace(/\.[^.]+$/, ''), b64: await toWavDataUri(d.data), sec: d.sec, color: '#9aa0c0',
          trail: [f.type.startsWith('video') ? '動画' : 'ファイル'], state: 'ready' });
      } catch {
        setError(`${f.name}は音声として読み込めませんでした`);
      }
    }
    setBusy(false);
  };

  return (
    <aside className="bg-panel border border-line rounded-[20px] p-4 flex flex-col gap-3 min-w-0">
      <div className="flex items-center gap-2.5">
        <span className="w-9 h-9 rounded-xl grid place-items-center bg-[#27e0c426] text-accent2"><Inbox size={18} /></span>
        <h2 className="text-lg font-extrabold">素材トレイ</h2>
        <span className="ml-auto text-[11px] font-bold px-2 py-0.5 rounded-full bg-line text-sub tabular-nums">{clips.length}本</span>
      </div>
      <label
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) void putFiles(e.dataTransfer.files); }}
        className={`flex items-center justify-center gap-2 p-2.5 rounded-xl border-2 border-dashed text-[13px] cursor-pointer transition ${
          over ? 'border-accent2 bg-accent2/10' : 'border-[#3a3f63] text-[#b9bedb] hover:border-accent2'}`}>
        {busy ? <Loader2 size={16} className="animate-spin text-accent2" /> : <Upload size={16} className="text-accent2" />}
        ファイルを置く
        <input type="file" accept="audio/*,video/*" multiple className="sr-only"
          onChange={(e) => { if (e.target.files?.length) void putFiles(e.target.files); e.target.value = ''; }} />
      </label>
      {error && <p className="text-xs text-[#ff8aa3]">{error}</p>}
      {clips.length === 0 && (
        <p className="text-xs text-sub text-center py-6">ツールで作った音声がここにたまります</p>
      )}
      <div className="flex flex-col gap-2.5 overflow-y-auto">
        {clips.map((c) => <Card key={c.id} c={c} onRemove={() => remove(c.id)}
          onUse={(k) => setTool(k, c.id)} onUpdate={(p) => update(c.id, p)} />)}
      </div>
    </aside>
  );
}

function Card({ c, onRemove, onUse, onUpdate }: {
  c: Clip; onRemove: () => void; onUse: (k: (typeof TOOLS)[number]['key']) => void; onUpdate: (p: Partial<Clip>) => void;
}) {
  const router = useRouter();
  const setSource = useCanvaStore((s) => s.setSource);
  const [menu, setMenu] = useState(false);
  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const short = c.sec < ANCHOR_MIN_SEC;

  const toAnchor = async () => {
    setSending(true); setMsg(null);
    try {
      await canvaApi.upload(c.b64, `${c.name}.wav`);
      onUpdate({ sentToAnchor: true });
    } catch (e) {
      setMsg(`送れませんでした: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSending(false);
    }
  };
  const toSource = () => {
    setSource({ kind: 'file', b64: c.b64, label: c.name, credit: null });
    void router.push('/');
  };
  const save = () => {
    const a = document.createElement('a');
    a.href = c.b64;
    a.download = `${c.name}.wav`;
    a.click();
  };
  const btn = 'inline-flex items-center gap-1.5 min-h-[32px] px-2.5 rounded-[9px] border border-line bg-panel text-xs hover:border-accent transition disabled:opacity-40';

  return (
    <div className="flex flex-col gap-2 p-3 rounded-2xl bg-panel2 border border-line">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-bold text-[13px] truncate" title={c.name}>{c.name}</span>
        {short && c.state === 'ready' && (
          <span className="text-[11px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap text-[#f2b84b] bg-[#f2b84b22]">{ANCHOR_MIN_SEC}秒未満</span>
        )}
        <span className="ml-auto font-mono text-xs text-sub">{c.state === 'ready' ? fmt(c.sec) : ''}</span>
        <button onClick={onRemove} aria-label={`${c.name}をトレイから消す`} className="text-sub hover:text-white"><X size={14} /></button>
      </div>
      <div className="text-[11px] text-sub">{c.trail.join(' → ')}</div>
      {c.state === 'busy' && (
        <div className="flex items-center gap-2 text-xs text-[#c4b5fd]"><Loader2 size={15} className="animate-spin" />作っています</div>
      )}
      {c.state === 'error' && <div className="text-xs text-[#ff8aa3]">{c.error}</div>}
      {c.state === 'ready' && (
        <>
          <WavePlayer src={c.b64} color={c.color} />
          <div className="flex flex-wrap gap-1.5">
            <div className="relative" ref={menuRef}>
              <button className={btn} onClick={() => setMenu((m) => !m)} aria-expanded={menu}><ArrowRight size={13} />ツールに回す</button>
              {menu && (
                <div className="absolute z-20 left-0 top-full mt-1 w-48 p-1 rounded-xl bg-panel border border-line shadow-xl">
                  {TOOLS.filter((t) => t.key !== 'extract' && t.key !== 'record').map((t) => (
                    <button key={t.key} onClick={() => { setMenu(false); onUse(t.key); }}
                      className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-sm hover:bg-panel2 text-left">
                      <t.Icon size={15} style={{ color: t.color }} />{t.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {c.sentToAnchor ? (
              <Link href="/anchors" className={`${btn} text-[#34d399]`}><Check size={13} />確認に送りました</Link>
            ) : (
              <button className={btn} onClick={toAnchor} disabled={short || sending}
                title={short ? `${ANCHOR_MIN_SEC}秒以上でアンカーに使えます` : 'アンカー管理と同じ確認に送ります'}>
                {sending ? <Loader2 size={13} className="animate-spin" /> : <UserPlus size={13} className="text-[#34d399]" />}アンカーに追加
              </button>
            )}
            <button className={btn} onClick={toSource}><AudioLines size={13} className="text-accent2" />元の音声に使う</button>
            <button className={btn} onClick={save} aria-label="保存"><Download size={13} /></button>
          </div>
          {msg && <p className="text-xs text-[#ff8aa3]">{msg}</p>}
        </>
      )}
    </div>
  );
}
