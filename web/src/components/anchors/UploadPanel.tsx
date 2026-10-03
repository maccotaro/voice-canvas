// アンカー管理: 素材の追加（ファイル or その場で録音 → 変換 → 送信 → サーバーで選定・品質チェック）
// どちらの入口も同じ確認を通る。止めるのは「短すぎる」「話し声が無い」だけで、1人の声か・録音品質が
// 基準に届かないものも採用して注意を出す（気軽に試せるように。気に入らなければ外す・削除する）。
import { useCallback, useEffect, useRef, useState } from 'react';
import { Upload, Loader2, CheckCircle2, XCircle, AlertTriangle, Trash2, Mic } from 'lucide-react';
import Link from 'next/link';
import { WavRecorder } from '@/lib/wavRecorder';
import { canvaApi } from '@/lib/api/canvaApi';
import { prepareAudio, MAX_SEC, MIN_SEC } from '@/lib/audioPrep';
import type { UploadJob } from '@/types/canva';

// ブラウザ側で変換・送信中のもの（サーバーに届く前）
interface LocalItem { key: string; filename: string; state: 'converting' | 'sending' | 'failed'; reason?: string }

const STATUS: Record<UploadJob['status'], string> = {
  queued: '順番待ち', processing: '処理中', accepted: '採用', rejected: '不採用', error: 'エラー',
};

export default function UploadPanel({ onChanged }: { onChanged: () => void }) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [local, setLocal] = useState<LocalItem[]>([]);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const seenAccepted = useRef<Set<string>>(new Set());
  // その場で録音
  const recRef = useRef<WavRecorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [recSec, setRecSec] = useState(0);
  const [recError, setRecError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const js = await canvaApi.uploads();
      setJobs(js);
      // 新しく採用されたら一覧を更新してもらう
      const fresh = js.filter((j) => j.status === 'accepted' && !seenAccepted.current.has(j.id));
      if (fresh.length) {
        fresh.forEach((j) => seenAccepted.current.add(j.id));
        onChanged();
      }
    } catch { /* 一時的な失敗は次の周期で取り直す */ }
  }, [onChanged]);

  useEffect(() => { refresh(); }, [refresh]);
  const busy = jobs.some((j) => j.status === 'queued' || j.status === 'processing');
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  const addFiles = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      const key = `${f.name}-${f.size}-${Date.now()}-${Math.random()}`;
      setLocal((l) => [...l, { key, filename: f.name, state: 'converting' }]);
      try {
        const prep = await prepareAudio(f);
        if (prep.sec < MIN_SEC) {
          throw new Error(`短すぎます（${prep.sec.toFixed(0)}秒）。${MIN_SEC}秒以上の録音を使ってください`);
        }
        setLocal((l) => l.map((x) => (x.key === key ? { ...x, state: 'sending' } : x)));
        await canvaApi.upload(prep.b64, f.name);
        setLocal((l) => l.filter((x) => x.key !== key));
        refresh();
      } catch (e) {
        const reason = e instanceof DOMException || String(e).includes('decode')
          ? 'このファイルは音声として読み込めませんでした'
          : String(e instanceof Error ? e.message : e);
        setLocal((l) => l.map((x) => (x.key === key ? { ...x, state: 'failed', reason } : x)));
      }
    }
  };

  useEffect(() => {
    if (!recording) return;
    const t0 = Date.now();
    const id = setInterval(() => setRecSec((Date.now() - t0) / 1000), 200);
    return () => clearInterval(id);
  }, [recording]);
  useEffect(() => () => recRef.current?.dispose(), []);
  const startRec = async () => {
    setRecError(null);
    try {
      recRef.current = new WavRecorder();
      await recRef.current.start();
      setRecSec(0);
      setRecording(true);
    } catch (e) {
      setRecError(`マイクを使えません（ブラウザでマイクを許可してください）: ${e}`);
    }
  };
  const stopRec = async () => {
    setRecording(false);
    try {
      const blob = await recRef.current?.stop();
      recRef.current = null;
      if (!blob) return;
      const d = new Date();
      const stamp = `${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
      // ファイルと同じ流れ（変換 → 長さの確認 → 送信 → サーバーで品質チェック）に乗せる
      await addFiles([new File([blob], `録音 ${stamp}.wav`, { type: 'audio/wav' })]);
    } catch (e) {
      setRecError(`録音を確定できませんでした: ${e}`);
    }
  };
  // 使う長さ（先頭 MAX_SEC 秒）に達したら自動で止める
  useEffect(() => { if (recording && recSec >= MAX_SEC) void stopRec(); }); // eslint-disable-line react-hooks/exhaustive-deps

  const clearDone = async () => {
    setLocal((l) => l.filter((x) => x.state !== 'failed'));
    try { setJobs(await canvaApi.clearUploads()); } catch { /* 次回の更新で反映 */ }
  };
  const hasDone = local.some((x) => x.state === 'failed')
    || jobs.some((j) => j.status === 'accepted' || j.status === 'rejected' || j.status === 'error');

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sub text-sm">
          ファイルか、その場の録音から気軽に追加できます。落ち着いて話している区間を探してアンカーにします。
          録音品質が低めのときなどは、追加したうえで注意を出します。
          動画から声を取り出したり、BGMを除いたり、使う区間を切り出したりするなら <Link href="/tools" className="text-accent2 underline">素材ツール</Link> へ。
        </p>
      </div>

      <ul className="text-sm text-sub grid gap-1 sm:grid-cols-2">
        <li>・1ファイルに1人の話し声だけ</li>
        <li>・{MIN_SEC}秒以上（20〜30秒あると選べる区間が増えます。先頭{MAX_SEC / 60}分まで使います）</li>
        <li>・静かな場所だと声がきれいに残ります</li>
        <li>・使ってよい声だけ（本人の同意がある録音やCC0のコーパスなど）</li>
      </ul>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label
        htmlFor="anchor-files"
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}
        className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 cursor-pointer transition text-center ${
          drag ? 'border-accent2 bg-[rgba(39,224,196,0.06)]' : 'border-line hover:border-accent'
        }`}
      >
        <Upload size={22} className="text-accent2" />
        <span className="text-sm font-bold">ファイルから</span>
        <span className="text-sm">ドロップ、またはクリックして選択（複数可）</span>
        <span className="text-xs text-sub">WAV・MP3・M4Aなど。確認には1本あたり数分かかります</span>
        <input
          ref={inputRef} id="anchor-files" type="file" accept="audio/*" multiple className="sr-only"
          onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ''; }}
        />
      </label>

        <div className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 px-4 py-6 text-center transition ${
          recording ? 'border-[#f472b6] bg-[#f472b60d]' : 'border-dashed border-line'}`}>
          <button onClick={recording ? stopRec : startRec} aria-label={recording ? '録音を止めて確認に送る' : '録音を始める'}
            className="w-14 h-14 rounded-full grid place-items-center transition hover:brightness-110"
            style={{ background: '#f472b6', boxShadow: recording ? '0 0 0 6px #f472b633, 0 0 0 12px #f472b614' : 'none' }}>
            {recording ? <span className="w-5 h-5 rounded bg-white" /> : <Mic size={24} className="text-bg" />}
          </button>
          <span className="text-sm font-bold">{recording ? '録音中' : 'その場で録音'}</span>
          {recording ? (
            <div className="w-full max-w-[280px] flex flex-col gap-1">
              {/* 最低の長さ（MIN_SEC）までの進み具合。超えたら緑にする */}
              <div className="h-2 rounded-full bg-line overflow-hidden">
                <div className="h-full rounded-full transition-all"
                  style={{ width: `${Math.min(100, (recSec / 30) * 100)}%`, background: recSec >= MIN_SEC ? '#34d399' : '#f472b6' }} />
              </div>
              <div className="flex justify-between text-xs">
                <span className="font-mono tabular-nums">{Math.floor(recSec / 60)}:{String(Math.floor(recSec % 60)).padStart(2, '0')}</span>
                <span className={recSec >= MIN_SEC ? 'text-[#34d399]' : 'text-sub'}>
                  {recSec >= MIN_SEC ? '止めると確認に送ります' : `あと${Math.ceil(MIN_SEC - recSec)}秒`}
                </span>
              </div>
            </div>
          ) : (
            <span className="text-xs text-sub">{MIN_SEC}秒以上、ふだんの声で。20〜30秒がおすすめ</span>
          )}
          {recError && <span className="text-xs text-[#ff8aa3]">{recError}</span>}
        </div>
      </div>

      {(local.length > 0 || jobs.length > 0) && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">処理の状況</h3>
            {hasDone && (
              <button onClick={clearDone} className="text-xs text-sub hover:text-white inline-flex items-center gap-1">
                <Trash2 size={13} />終わったものを消す
              </button>
            )}
          </div>
          <ul className="divide-y divide-line border border-line rounded-xl overflow-hidden">
            {local.map((x) => (
              <li key={x.key} className="px-3 py-2.5 text-sm flex items-start gap-2 bg-panel2">
                {x.state === 'failed'
                  ? <XCircle size={16} className="text-[#ff8aa3] mt-0.5 shrink-0" />
                  : <Loader2 size={16} className="animate-spin text-sub mt-0.5 shrink-0" />}
                <div className="min-w-0">
                  <div className="truncate">{x.filename}</div>
                  <div className="text-xs text-sub">
                    {x.state === 'converting' ? '変換中' : x.state === 'sending' ? '送信中' : x.reason}
                  </div>
                </div>
              </li>
            ))}
            {jobs.map((j) => <JobRow key={j.id} j={j} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

function JobRow({ j }: { j: UploadJob }) {
  const warn = j.status === 'accepted' && (j.warnings?.length ?? 0) > 0;
  const icon = j.status === 'accepted'
    ? <CheckCircle2 size={16} className={`${warn ? 'text-amber-300' : 'text-accent2'} mt-0.5 shrink-0`} />
    : j.status === 'rejected' ? <AlertTriangle size={16} className="text-amber-300 mt-0.5 shrink-0" />
      : j.status === 'error' ? <XCircle size={16} className="text-[#ff8aa3] mt-0.5 shrink-0" />
        : <Loader2 size={16} className="animate-spin text-sub mt-0.5 shrink-0" />;
  return (
    <li className="px-3 py-2.5 text-sm flex items-start gap-2 bg-panel2">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="truncate">{j.filename}</span>
          <span className="text-xs text-sub tabular-nums">{j.sec.toFixed(0)}秒</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-panel border border-line">
            {STATUS[j.status]}{j.status === 'accepted' && j.name ? `（${j.name}）` : ''}
          </span>
          {warn && <span className="text-xs px-1.5 py-0.5 rounded bg-amber-300/15 text-amber-300">注意あり</span>}
        </div>
        {warn && j.warnings!.map((w) => <div key={w} className="text-xs text-amber-200/90">・{w}</div>)}
        {j.status === 'processing' && j.step && <div className="text-xs text-sub">{j.step}</div>}
        {j.reason && <div className="text-xs text-sub">{j.reason}</div>}
        {j.metrics && (
          <div className="text-xs text-sub tabular-nums mt-0.5">
            録音品質 {j.metrics.quality.toFixed(2)}（目安 2.3）・1人の声 {j.metrics.single != null ? j.metrics.single.toFixed(2) : '—'}（目安 0.55）・声の高さ {j.metrics.f0}Hz
          </div>
        )}
      </div>
    </li>
  );
}
