// 素材ツール: 録音や動画を、声づくりの素材に整える。左=ツール / 中央=選んだツール / 右=素材トレイ。
// 音声抽出・カット・ピッチ・結合・録音はブラウザの中で、BGM・雑音の除去は推論サービス（Demucs）で処理する。
import Link from 'next/link';
import { ArrowLeft, Users, Wrench, BookOpen } from 'lucide-react';
import { useToolsStore } from '@/stores/toolsStore';
import { TOOLS } from '@/components/tools/common';
import Tray from '@/components/tools/Tray';
import ExtractTool from '@/components/tools/ExtractTool';
import SeparateTool, { useSeparateWatcher } from '@/components/tools/SeparateTool';
import CutTool from '@/components/tools/CutTool';
import PitchTool from '@/components/tools/PitchTool';
import JoinTool from '@/components/tools/JoinTool';
import RecordTool from '@/components/tools/RecordTool';

const PANELS = { extract: ExtractTool, separate: SeparateTool, cut: CutTool, pitch: PitchTool, join: JoinTool, record: RecordTool };

export default function ToolsPage() {
  const { tool, setTool, sep } = useToolsStore();
  useSeparateWatcher();   // BGM除去は画面を移っても裏で進める
  const Panel = PANELS[tool];
  const running = sep.filter((w) => w.job.status === 'queued' || w.job.status === 'processing').length;

  return (
    <div className="min-h-screen flex flex-col">
      <header className="px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 border-b border-line">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent grid place-items-center text-white"><Wrench size={19} /></div>
          <div>
            <h1 className="text-lg font-extrabold leading-tight">素材ツール</h1>
            <p className="text-sub text-xs">録音や動画を、声づくりの素材に整える</p>
          </div>
        </div>
        <nav className="flex gap-2">
          <Link href="/" className="btn whitespace-nowrap"><ArrowLeft size={15} />声のデザイン</Link>
          <Link href="/anchors" className="btn whitespace-nowrap"><Users size={15} />アンカー管理</Link>
          <Link href="/manual#tools" className="btn whitespace-nowrap"><BookOpen size={15} />使い方</Link>
        </nav>
      </header>

      <main className="flex-1 grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)_380px] gap-5 p-5 items-start">
        <aside className="bg-panel border border-line rounded-[20px] p-3.5 flex flex-col gap-1.5 lg:sticky lg:top-5">
          <span className="text-xs text-sub px-2 py-1">ツール</span>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-1 gap-1.5">
            {TOOLS.map((t) => {
              const on = t.key === tool;
              return (
                <button key={t.key} onClick={() => setTool(t.key)} aria-current={on ? 'page' : undefined}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-[14px] text-left transition"
                  style={on ? { background: `${t.color}1f`, border: `2px solid ${t.color}` } : { border: '2px solid transparent' }}>
                  <span className="w-10 h-10 shrink-0 rounded-xl grid place-items-center"
                    style={on ? { background: t.color, color: '#0b0d17' } : { background: `${t.color}26`, color: t.color }}>
                    <t.Icon size={19} />
                  </span>
                  <span className="flex flex-col leading-snug min-w-0">
                    <span className={`text-sm ${on ? 'font-extrabold' : 'font-bold'}`}>{t.label}</span>
                    <span className="text-[11px] text-sub truncate">{t.key === 'separate' && running > 0 ? `${running}本を処理中` : t.sub}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="hidden lg:block mt-3 p-3 rounded-[14px] bg-[#17142e] border border-[#3b3470] text-xs leading-relaxed text-[#d6d9ef]">
            <span className="font-extrabold text-[#e879f9]">たとえば</span><br />
            動画 → <span className="text-[#60a5fa]">抽出</span> → <span className="text-[#a78bfa]">BGM除去</span> → <span className="text-[#fb923c]">カット</span> → アンカーに追加
          </div>
        </aside>

        <section className="bg-panel border border-line rounded-[20px] p-5 flex flex-col gap-4 min-w-0 min-h-[640px]">
          <Panel key={tool} />
        </section>

        <Tray />
      </main>
    </div>
  );
}
