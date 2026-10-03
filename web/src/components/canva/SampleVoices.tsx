// こんな声が作れます: このアプリで作ったサンプル音声。押すと聴けて、その声の設定が「声の設定」に入る。
// 音声は scripts/gen_persona_samples.py、顔は scripts/gen_persona_avatars.py で作った同梱ファイル。
// preset は音声を作ったときと同じ値（scripts/gen_persona_samples.py の PERSONAS と揃える）。
import { useRef, useState } from 'react';
import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { useCanvaStore } from '@/stores/canvaStore';

const SAMPLES = [
  { key: 'natural_female', name: 'ナチュラル女性', color: '#2fae94',
    preset: { age: 40, gender: 80, pitch: 60, build: 60, huskiness: 30, clarity: 65, warmth: 60, roughness: 25 } },
  { key: 'calm_male', name: '落ち着いた男性', color: '#60a5fa',
    preset: { age: 90, gender: 10, pitch: 15, build: 20, huskiness: 55, clarity: 50, warmth: 62, roughness: 55 } },
  { key: 'intellectual_male', name: '知的な語り口', color: '#a78bfa',
    preset: { age: 60, gender: 12, pitch: 30, build: 45, huskiness: 15, clarity: 88, warmth: 30, roughness: 12 } },
  { key: 'warm_narration', name: '温かいナレーション', color: '#fb923c',
    preset: { age: 70, gender: 80, pitch: 45, build: 40, huskiness: 35, clarity: 60, warmth: 92, roughness: 30 } },
  { key: 'friendly_female', name: '親しみやすい声', color: '#fb7185',
    preset: { age: 30, gender: 85, pitch: 55, build: 60, huskiness: 20, clarity: 72, warmth: 85, roughness: 15 } },
  { key: 'energetic_male', name: '活発な男性', color: '#f2b84b',
    preset: { age: 15, gender: 10, pitch: 45, build: 55, huskiness: 30, clarity: 80, warmth: 45, roughness: 60 } },
];
const BASE = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/personas`;

export default function SampleVoices() {
  const ref = useRef<HTMLAudioElement | null>(null);
  const setSliders = useCanvaStore((st) => st.setSliders);
  const [playing, setPlaying] = useState<string | null>(null);

  // 押すとサンプルを聴けて、同時にその声の設定がグラフとスライダーに入る
  const play = (key: string) => {
    const el = ref.current;
    if (!el) return;
    if (playing === key) { el.pause(); setPlaying(null); return; }
    const s = SAMPLES.find((x) => x.key === key);
    if (s) setSliders(s.preset);
    el.src = `${BASE}/${key}.wav`;
    setPlaying(key);
    el.play().catch(() => setPlaying(null));
  };

  return (
    <div className="flex flex-wrap items-center gap-2 pl-3.5 pr-1.5 py-1 rounded-[22px] bg-[#17142e] border border-[#3b3470]">
      <span className="text-xs font-bold text-[#e879f9] whitespace-nowrap">こんな声が作れます</span>
      {SAMPLES.map((s) => (
        <button key={s.key} onClick={() => play(s.key)} title={s.name}
          aria-label={playing === s.key ? `${s.name}を止める` : `${s.name}を聴いて設定に入れる`}
          className="relative w-9 h-9 p-0 rounded-full overflow-hidden bg-panel2 transition hover:scale-110"
          style={{ border: `2px solid ${s.color}`, boxShadow: playing === s.key ? `0 0 0 3px ${s.color}66` : 'none' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`${BASE}/avatars/${s.key}.svg`} alt="" className="w-full h-full" />
          {playing === s.key && <span className="absolute inset-0 bg-black/40 grid place-items-center text-white text-[10px]">■</span>}
        </button>
      ))}
      <Link href="/anchors"
        className="ml-1 pl-3 pr-2.5 h-9 inline-flex items-center gap-1 rounded-full text-xs font-bold whitespace-nowrap text-white hover:brightness-110 transition"
        style={{ background: 'linear-gradient(90deg, #7c5cff, #e879f9)' }}>
        もっといろいろな声を作りたい<ChevronRight size={14} />
      </Link>
      <audio ref={ref} className="hidden" onEnded={() => setPlaying(null)} />
    </div>
  );
}
