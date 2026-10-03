// アンカーのしくみ: 登録した声（アンカー）を混ぜて新しい声を作る、を絵で見せる。
// スライダーで決めた特徴に近いアンカーを自動で選び、近い順に重みをつけて混ぜる（voice_canva/design.py）。
import { User, Plus, SlidersHorizontal, Sparkles, ArrowRight, Users, Mic, Shuffle } from 'lucide-react';

const A = '#27e0c4';
const B = '#fb923c';

function Person({ name, note, color }: { name: string; note: string; color: string }) {
  return (
    <div className="flex flex-col items-center gap-1.5 w-[104px]">
      <span className="w-[72px] h-[72px] rounded-full grid place-items-center relative"
        style={{ background: `${color}26`, border: `3px solid ${color}` }}>
        <User size={34} style={{ color }} />
        <span className="absolute -bottom-1 -right-1 w-7 h-7 rounded-full grid place-items-center text-[13px] font-extrabold text-bg"
          style={{ background: color }}>{name}</span>
      </span>
      <span className="text-sm font-bold">{name}さん</span>
      <span className="text-[11px] px-2 py-0.5 rounded-full font-bold" style={{ color, background: `${color}22` }}>{note}</span>
    </div>
  );
}

function Mix({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-12 font-bold" style={{ color }}>{label}</span>
      <span className="flex-1 h-2.5 rounded-full bg-line overflow-hidden">
        <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </span>
      <span className="w-9 text-right font-mono tabular-nums">{pct}%</span>
    </div>
  );
}

export default function HowItWorks() {
  return (
    <div className="flex flex-col gap-5 overflow-hidden">
      {/* アンカーを知らない人向けに、まず何なのかを言う */}
      <p className="text-[15px] leading-relaxed">
        アンカーは、人が話している<b className="text-[#e879f9]">12秒ほどの音声</b>です。さまざまなアンカーを登録して、無限の声を作りましょう。
      </p>

      {/* Aさん ＋ Bさん → 混ぜ具合 → 新しい声 */}
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-5 py-2">
        <div className="flex items-center gap-2">
          <Person name="A" note="やわらかい声" color={A} />
          <Plus size={22} className="text-sub" />
          <Person name="B" note="ハスキー" color={B} />
        </div>
        <ArrowRight size={26} className="text-sub hidden sm:block" />
        <div className="w-[220px] flex flex-col gap-2 p-3.5 rounded-2xl bg-panel2 border border-line">
          <span className="flex items-center gap-1.5 text-xs font-bold text-[#a78bfa]"><SlidersHorizontal size={14} />混ぜ具合</span>
          <Mix label="Aさん" pct={70} color={A} />
          <Mix label="Bさん" pct={30} color={B} />
        </div>
        <ArrowRight size={26} className="text-sub hidden sm:block" />
        <div className="flex flex-col items-center gap-2 max-w-[230px]">
          <span className="w-[84px] h-[84px] rounded-full grid place-items-center"
            style={{ background: `conic-gradient(${A} 0 70%, ${B} 70% 100%)` }}>
            <span className="w-[68px] h-[68px] rounded-full bg-panel grid place-items-center">
              <Sparkles size={32} className="text-[#e879f9]" />
            </span>
          </span>
          <span className="text-sm font-bold">新しい声</span>
          <span className="relative text-[13px] leading-snug text-center px-3.5 py-2 rounded-2xl bg-[#17142e] border border-[#3b3470]">
            「<span style={{ color: A }} className="font-bold">Aさん</span>に似てるけど、<br />
            <span style={{ color: B }} className="font-bold">Bさん</span>のハスキーな感じ」
          </span>
        </div>
      </div>

      {/* 3つのポイント */}
      <ul className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {[
          { Icon: Shuffle, c: '#a78bfa', t: '混ぜ具合は自動', d: '声の設定のスライダーに近いアンカーを選んで混ぜます' },
          { Icon: Users, c: '#60a5fa', t: '多いほど広がる', d: '性別・年代・声質がばらけるほど、作れる声が増えます' },
          { Icon: Mic, c: '#f472b6', t: '自分で足せる', d: '下の「素材を追加」を使います。使ってよい声だけにしてください' },
        ].map(({ Icon, c, t, d }) => (
          <li key={t} className="flex items-start gap-3 p-3.5 rounded-2xl bg-panel2 border border-line">
            <span className="w-10 h-10 shrink-0 rounded-xl grid place-items-center" style={{ background: `${c}26`, color: c }}><Icon size={20} /></span>
            <span className="flex flex-col">
              <span className="text-sm font-bold">{t}</span>
              <span className="text-xs text-[#b9bedb]">{d}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
