// アンカー管理ページ（初回セットアップ兼用）
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AudioLines, ArrowLeft, Sparkles, Upload, BookOpen } from 'lucide-react';
import { canvaApi } from '@/lib/api/canvaApi';
import UploadPanel from '@/components/anchors/UploadPanel';
import AnchorList from '@/components/anchors/AnchorList';
import HowItWorks from '@/components/anchors/HowItWorks';
import Fold from '@/components/anchors/Fold';
import type { AnchorOverview } from '@/types/canva';

export default function AnchorsPage() {
  const [data, setData] = useState<AnchorOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setData(await canvaApi.anchorsAdmin()); setError(null); }
    catch (e) { setError(`推論サービスに接続できません: ${e instanceof Error ? e.message : e}`); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const n = data?.anchors.length ?? 0;
  const min = data?.min_anchors ?? 3;

  return (
    <div className="min-h-screen flex flex-col">
      <header className="px-5 py-3.5 flex items-center justify-between border-b border-line">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent grid place-items-center text-white"><AudioLines size={20} /></div>
          <div>
            <h1 className="text-lg font-extrabold leading-tight">アンカー管理</h1>
            <p className="text-sub text-xs">声の材料になる音声（アンカー）を登録します</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Link href="/manual#anchors" className="btn whitespace-nowrap shrink-0"><BookOpen size={15} />使い方</Link>
          <Link href="/" className="btn whitespace-nowrap shrink-0"><ArrowLeft size={15} />声のデザインへ</Link>
        </div>
      </header>

      <main className="flex-1 p-5 space-y-5 max-w-[1400px] w-full mx-auto min-w-0">
        {error && (
          <div className="p-3 rounded-lg bg-[rgba(255,92,124,0.1)] border border-[rgba(255,92,124,0.3)] text-sm text-[#ff8aa3]">
            {error}
          </div>
        )}

        {/* いまの状態。人数が増減しても高さが変わらないよう、いつも同じ1行の欄に出す（下の操作位置がずれないように） */}
        {data && (
          <div className={`min-h-[52px] px-4 py-2.5 rounded-xl border flex flex-wrap items-center gap-x-3 gap-y-1 text-sm ${
            data.ready ? 'bg-panel border-line' : 'bg-[#2a2412] border-[#5a4a1a]'}`}>
            <span className="w-2.5 h-2.5 shrink-0 rounded-full" style={{ background: data.ready ? '#34d399' : '#f2b84b' }} />
            {data.ready ? (
              <span><span className="font-bold tabular-nums">{n}人</span> 登録済み。声のデザインに使えます。</span>
            ) : (
              <span className="text-[#f2d58b]">
                声を作るには<b>{min}人以上</b>必要です（いまは<b className="tabular-nums">{n}人</b>で、あと{Math.max(0, min - n)}人）。
                {data.excluded.length > 0 ? '下の表の「外したアンカー」から戻すか、' : ''}「素材を追加」から録音を追加してください。
              </span>
            )}
          </div>
        )}

        <Fold id="how" title="アンカーは、新しい声の材料です" Icon={Sparkles} color="#e879f9">
          <HowItWorks />
        </Fold>
        <Fold id="upload" title="素材を追加" Icon={Upload} color="#34d399"
          badge={data && data.pending > 0
            ? <span className="text-[11px] font-bold px-2 py-0.5 rounded-full text-[#34d399] bg-[#34d39922]">{data.pending}本を処理中</span>
            : undefined}>
          <UploadPanel onChanged={load} />
        </Fold>
        {data && <AnchorList data={data} onUpdate={setData} onError={setError} />}
      </main>
    </div>
  );
}
