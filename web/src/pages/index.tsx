// 声のCanva メインページ。3列の作業台: 元の音声 → 声の設定 → 新しい声
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Download, Upload, AudioLines, Users, Wrench, BookOpen } from 'lucide-react';
import { useCanvaStore } from '@/stores/canvaStore';
import { canvaApi } from '@/lib/api/canvaApi';
import { decodeSliders } from '@/lib/voice';
import IrodoriPanel from '@/components/canva/IrodoriPanel';
import SourcePanel from '@/components/canva/SourcePanel';
import DesignPanel from '@/components/canva/DesignPanel';
import TakesPanel from '@/components/canva/TakesPanel';
import SampleVoices from '@/components/canva/SampleVoices';
import ExtrasPanel from '@/components/canva/ExtrasPanel';

// デザインモード: seedvc=意味軸スライダー(Seed-VC) / irodori=キャプション+seed(Irodori-TTS)
type DesignMode = 'seedvc' | 'irodori';

// 声の設定を JSON で書き出す（voice-canvas-settings-日時.json）
function exportSettings(sliders: Record<string, number>, adv: unknown) {
  const blob = new Blob([JSON.stringify({ app: 'voice-canvas', version: 1, sliders, adv }, null, 2)],
    { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `voice-canvas-settings-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export default function Home() {
  const { sliders, adv, setAxes, setAnchors, setSliders, setAdv } = useCanvaStore();
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<DesignMode>('seedvc');
  // キャプション（Irodori-TTS）は別サーバーが必要。つながらない環境ではタブを出さない
  const [irodoriOk, setIrodoriOk] = useState(false);
  // アンカー不足（初回セットアップ前・外しすぎ）なら案内を出す: [登録数, 必要数, 外した数]
  const [setup, setSetup] = useState<[number, number, number] | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [ax, an, ov] = await Promise.all([canvaApi.axes(), canvaApi.anchors(), canvaApi.anchorsAdmin()]);
        setAxes(ax);
        setAnchors(an);
        if (!ov.ready) setSetup([ov.anchors.length, ov.min_anchors, ov.excluded.length]);
        const sp = new URLSearchParams(window.location.search).get('s');
        const restored = sp && decodeSliders(sp);
        if (restored) setSliders(restored);
      } catch (e) {
        setError(`推論サービスに接続できません: ${e}`);
      }
    })();
  }, [setAxes, setAnchors, setSliders]);

  useEffect(() => {
    // 中継(BFF)は Irodori サーバーにつながらないときだけ 502 を返す。それ以外の応答ならサーバーはある
    fetch(`${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/api/irodori/v1/models`)
      .then((r) => setIrodoriOk(r.status !== 502))
      .catch(() => setIrodoriOk(false));
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      {/* ヘッダー */}
      <header className="px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 border-b border-line">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent grid place-items-center text-white">
            <AudioLines size={20} />
          </div>
          <div>
            <h1 className="text-lg font-extrabold leading-tight">
              Voice Canvas <span className="text-[11px] bg-accent px-1.5 py-0.5 rounded ml-1 align-middle">β版</span>
            </h1>
            <p className="text-sub text-xs">声のデザインを、もっと自由に。</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <div className={mode === 'irodori' ? 'hidden' : 'hidden md:block'}><SampleVoices /></div>
          {/* モード切替: スライダー(Seed-VC) / キャプション(Irodori)。Irodori が無ければ出さない */}
          <div className={irodoriOk ? 'flex rounded-lg border border-line overflow-hidden text-sm' : 'hidden'}>
            {(
              [
                ['seedvc', 'スライダー'],
                ['irodori', 'キャプション'],
              ] as [DesignMode, string][]
            ).map(([m, label]) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1.5 transition ${
                  mode === m ? 'bg-accent text-white' : 'bg-panel2 text-sub hover:text-white'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <Link href="/tools" className="btn"><Wrench size={15} />素材ツール</Link>
          <Link href="/manual" className="btn"><BookOpen size={15} />使い方</Link>
          {/* 声の設定（スライダー・話す速さなど）をファイルに書き出す／読み込む */}
          <button className="btn" onClick={() => exportSettings(sliders, adv)}><Download size={15} />設定を書き出す</button>
          <label className="btn cursor-pointer">
            <Upload size={15} />設定を読み込む
            <input type="file" accept="application/json,.json" className="sr-only" onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (!f) return;
              try {
                const j = JSON.parse(await f.text());
                if (!j || typeof j.sliders !== 'object') throw new Error('スライダーの設定が入っていません');
                setSliders(j.sliders);
                if (j.adv && typeof j.adv === 'object') setAdv(j.adv);
                setError(null);
              } catch (err) {
                setError(`設定ファイルを読み込めませんでした: ${err instanceof Error ? err.message : err}`);
              }
            }} />
          </label>
        </div>
      </header>

      {/* メイン */}
      <main className="flex-1 p-5 space-y-5 min-w-0">
          {error && (
            <div className="p-3 rounded-lg bg-[rgba(255,92,124,0.1)] border border-[rgba(255,92,124,0.3)] text-sm text-[#ff8aa3]">
              {error}（推論サービスを起動してください）
            </div>
          )}

          {setup && (
            <div className="p-4 rounded-xl bg-panel border border-accent/60 flex flex-col sm:flex-row sm:items-center gap-3">
              <div className="flex-1 text-sm">
                <div className="font-semibold">声をデザインする前に、アンカーを登録してください</div>
                <div className="text-sub">
                  基準になる話者の録音が{setup[1]}人以上必要です（いまは<span className="tabular-nums">{setup[0]}</span>人）。
                  {setup[2] > 0 && <>外したアンカー（{setup[2]}人）は、アンカー管理の「外したアンカー」から戻せます。</>}
                </div>
              </div>
              <Link href="/anchors" className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:brightness-110">
                <Users size={15} />アンカーを登録する
              </Link>
            </div>
          )}

          {/* Irodori モード: キャプション+seed の探索パネル(1カラム) */}
          {mode === 'irodori' && (
            <div className="max-w-2xl mx-auto w-full bg-panel border border-line rounded-2xl p-5">
              <IrodoriPanel />
            </div>
          )}

          {/* 3列の作業台: 元の音声 → 声の設定 → 新しい声（狭い画面では縦に積む） */}
          <div className={mode === 'irodori' ? 'hidden' : 'grid grid-cols-1 lg:grid-cols-[minmax(320px,360px)_minmax(0,1fr)_minmax(320px,380px)] gap-[22px] items-stretch'}>
            <SourcePanel />
            <DesignPanel />
            <TakesPanel />
          </div>
          <div className={mode === 'irodori' ? 'hidden' : 'md:hidden'}><SampleVoices /></div>
          {mode !== 'irodori' && <ExtrasPanel />}
        </main>
    </div>
  );
}
