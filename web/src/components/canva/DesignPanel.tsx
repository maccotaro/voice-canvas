// STEP 2 声の設定: レーダーチャートとスライダー（双方向に連動）で声を決め、元の音声をこの声に変換する。
import { SlidersHorizontal, Dices, AudioLines, Loader2 } from 'lucide-react';
import { useCanvaStore } from '@/stores/canvaStore';
import { axisMeta } from '@/lib/axisMeta';
import RadarChart from './RadarChart';
import { StepHead, FlowArrow } from './parts';

const C = '#a78bfa';

export default function DesignPanel() {
  const { axes, sliders, setSlider, randomize, generate, generating, source, takes } = useCanvaStore();
  const ready = !!source && axes.length > 0 && !generating;

  return (
    <section className="relative bg-panel border border-line rounded-[20px] p-5 flex flex-col gap-4 min-w-0">
      <FlowArrow active={takes.length > 0} color={C} />
      <StepHead n={2} title="声の設定" color={C} Icon={SlidersHorizontal} tag={`${axes.length}つの特徴`} tagColor={C}>
        <button onClick={randomize} disabled={axes.length === 0} className="btn min-h-[40px] px-3 rounded-xl shrink-0 ml-auto sm:ml-0">
          <Dices size={16} className="text-[#f2b84b]" />ランダム
        </button>
      </StepHead>

      <RadarChart axes={axes} sliders={sliders} />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-7 gap-y-2.5">
        {axes.map((a) => {
          const { color, Icon } = axisMeta(a.key);
          const val = Math.round(sliders[a.key] ?? 50);
          return (
            <label key={a.key} className="flex flex-col gap-0.5">
              <span className="flex items-center gap-2 text-sm">
                <span className="w-[26px] h-[26px] rounded-lg grid place-items-center" style={{ background: `${color}26`, color }}>
                  <Icon size={15} />
                </span>
                <span className="font-bold">{a.label}</span>
                <span className="ml-auto font-mono tabular-nums" style={{ color }}>{val}%</span>
              </span>
              <input type="range" min={0} max={100} step={1} value={sliders[a.key] ?? 50}
                onChange={(e) => setSlider(a.key, Number(e.target.value))}
                aria-label={`${a.label}（${a.low}〜${a.high}）`} className="w-full mt-1.5"
                style={{
                  ['--fill' as string]: color,
                  background: `linear-gradient(to right, ${color} 0%, ${color} ${val}%, #2a2f4d ${val}%, #2a2f4d 100%)`,
                }} />
              <span className="flex justify-between text-[11px] text-sub"><span>{a.low}</span><span>{a.high}</span></span>
            </label>
          );
        })}
      </div>

      {/* 左の小さな枠は元の音声。空なら点線で、押せない */}
      <button onClick={() => void generate()} disabled={!ready}
        className="mt-auto min-h-[56px] rounded-2xl bg-accent text-white text-[17px] font-bold inline-flex items-center justify-center gap-2.5 hover:brightness-110 transition disabled:opacity-50">
        {source
          ? <span className="w-[30px] h-[30px] rounded-lg bg-white/20 grid place-items-center">
              {generating ? <Loader2 size={16} className="animate-spin" /> : <AudioLines size={16} />}
            </span>
          : <span className="w-[30px] h-[30px] rounded-lg border-2 border-dashed border-white/50" />}
        {generating ? '変換中…' : 'この声に変換する'}
      </button>
    </section>
  );
}
