// BGM・雑音の除去: 声だけを残す（推論サービスの Demucs。CPU で音声の長さとほぼ同じ時間）。
// 処理は裏で進むので、ほかのツールを使っていてもよい。できるとトレイに入る。
import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { canvaApi } from '@/lib/api/canvaApi';
import type { SeparateJob } from '@/types/canva';
import { WavePlayer } from '@/components/canva/parts';
import { ToolHead, InputPick, Primary, toolOf, fmt } from './common';

const C = toolOf('separate').color;
const PESQ_OK = 2.3; // アンカー登録の録音品質の目安

function blobToDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onloadend = () => resolve(r.result as string);
    r.readAsDataURL(blob);
  });
}

// 素材ツールのページ全体で呼ぶ: 処理中のジョブの進み具合を取りに行き、できたらトレイに入れる
// （BGM除去の画面を離れても止まらないように）
export function useSeparateWatcher() {
  const { sep, update, updateSep } = useToolsStore();
  const pending = sep.filter((w) => w.job.status === 'queued' || w.job.status === 'processing');
  const key = pending.map((w) => w.job.id).join(',');
  useEffect(() => {
    if (!key) return;
    const tick = async () => {
      for (const w of useToolsStore.getState().sep) {
        if (w.job.status !== 'queued' && w.job.status !== 'processing') continue;
        try {
          const j = await canvaApi.separateStatus(w.job.id);
          if (j.status === 'done') {
            const b64 = await blobToDataUri(await (await fetch(canvaApi.separateAudioUrl(j.id))).blob());
            update(w.clipId, { b64, state: 'ready' });
          } else if (j.status === 'error') {
            update(w.clipId, { state: 'error', error: j.reason || 'できませんでした' });
          }
          updateSep(j);
        } catch { /* 一時的な失敗は次の周期で取り直す */ }
      }
    };
    const id = setInterval(tick, 2000);
    void tick();
    return () => clearInterval(id);
  }, [key, update, updateSep]);
}

function Quality({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="font-mono text-sub">—</span>;
  const ok = v >= PESQ_OK;
  return <span className="font-mono font-bold" style={{ color: ok ? '#34d399' : '#f2b84b' }}>{v.toFixed(2)}</span>;
}

export default function SeparateTool() {
  const { clips, inputId, add, sep, addSep } = useToolsStore();
  const input = clips.find((c) => c.id === inputId && c.state === 'ready');
  const [error, setError] = useState<string | null>(null);
  // この素材で最後に始めたジョブ（声だけにした結果を選んでいるときは、その元のジョブ）
  const w = input ? sep.find((x) => x.inputId === input.id) ?? sep.find((x) => x.clipId === input.id) : undefined;
  const before = w ? clips.find((c) => c.id === w.inputId) : input;
  const job = w?.job ?? null;
  const result = w ? clips.find((c) => c.id === w.clipId) : undefined;

  const start = async () => {
    if (!input) return;
    setError(null);
    try {
      const j = await canvaApi.separate(input.b64, `${input.name}.wav`);
      const clipId = add({ name: `${input.name}（声だけ）`, b64: '', sec: input.sec, color: C,
        trail: [...input.trail, 'BGM除去'], state: 'busy' });
      addSep({ job: j, clipId, inputId: input.id });
    } catch (e) {
      setError(`始められませんでした: ${e instanceof Error ? e.message : e}`);
    }
  };

  const running = job && (job.status === 'queued' || job.status === 'processing');
  const showing = !!job;
  const elapsed = job?.elapsed ?? 0;
  return (
    <>
      <ToolHead k="separate" />
      <InputPick clip={input} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        <div className="flex flex-col gap-2 p-3.5 rounded-2xl bg-panel2 border border-line">
          <span className="text-xs text-sub">いまの音</span>
          {before ? <WavePlayer src={before.b64} color={before.color} /> : <div className="h-[30px]" />}
          <div className="flex items-center gap-2 text-xs"><span className="text-sub">録音品質</span><Quality v={showing ? job?.quality_before : null} /></div>
        </div>
        <div className="flex flex-col gap-2 p-3.5 rounded-2xl"
          style={showing && result?.state === 'ready' ? { background: '#1d1a3a', border: `2px solid ${C}` } : { background: '#1d1a3a', border: `2px dashed ${C}88` }}>
          <span className="text-xs text-[#c4b5fd]">声だけ{showing && result?.state === 'ready' ? '' : '（できたら並べて比べられます）'}</span>
          {showing && result?.state === 'ready' ? <WavePlayer src={result.b64} color={C} /> : (
            <div className="h-[30px] flex items-center"><div className="flex-1 h-0.5" style={{ background: `repeating-linear-gradient(90deg, ${C}88 0 6px, transparent 6px 12px)` }} /></div>
          )}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-sub">録音品質</span><Quality v={showing ? job?.quality_after : null} />
            {showing && job?.quality_after != null && job.quality_after >= PESQ_OK && (
              <span className="text-[11px] font-bold px-2 py-0.5 rounded-full text-[#34d399] bg-[#34d39922]">目安の{PESQ_OK}を超えました</span>
            )}
          </div>
        </div>
      </div>

      {showing && running && (
        <div className="flex flex-col gap-2.5 p-4 rounded-2xl border-2 border-accent" style={{ background: 'linear-gradient(135deg, #2a1f55, #1b2a44)' }}>
          <div className="flex items-center gap-2.5">
            <Loader2 size={20} className="animate-spin" style={{ color: C }} />
            <strong className="font-extrabold">{job!.status === 'queued' ? '順番を待っています' : job!.step || '声とそれ以外を分けています'}</strong>
            <span className="ml-auto font-mono text-[#d6d9ef] tabular-nums">{fmt(elapsed)} / 約{fmt(job!.estimate)}</span>
          </div>
          <div className="h-2.5 rounded-full bg-line overflow-hidden">
            <div className="h-full rounded-full transition-all" style={{
              width: `${Math.min(95, (elapsed / Math.max(1, job!.estimate)) * 100)}%`,
              background: `linear-gradient(90deg, #60a5fa, ${C})` }} />
          </div>
          <span className="text-xs text-[#b9bedb]">CPUでは、音声の長さとほぼ同じ時間がかかります。初回だけ部品（約80MB）を取得します。待つあいだも、ほかのツールを使えます</span>
        </div>
      )}
      {showing && job?.status === 'error' && <p className="text-sm text-[#ff8aa3]">{job.reason}</p>}
      {error && <p className="text-sm text-[#ff8aa3]">{error}</p>}

      <div className="mt-auto">
        <Primary color={C} disabled={!input || !!(showing && running)} onClick={start}>声だけを残す</Primary>
      </div>
    </>
  );
}
