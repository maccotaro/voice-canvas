// 声のCanva: スライダー値(0..100)から「声の印象」(アイコン/タグ)・類似度・共有リンクを導く。
import type { Sliders, Axis } from '@/types/canva';

export interface VoiceTraits {
  emoji: string; // 声から想像されるアイコン
  tags: string[]; // 女性 / フレンドリー など
}

const v = (s: Sliders, k: string) => (s[k] ?? 50);

/** スライダー値から声の印象（アイコン＋タグ）を推定する。 */
export function voiceTraits(s: Sliders): VoiceTraits {
  const gender = v(s, 'gender'); // 高=女性的
  const age = v(s, 'age'); // 高=年配
  const young = age <= 38;
  const old = age >= 64;

  // アイコン: 性別 × 年齢感
  let emoji = '🧑';
  if (gender >= 58) emoji = old ? '👵' : young ? '👧' : '👩';
  else if (gender <= 42) emoji = old ? '👴' : young ? '👦' : '👨';
  else emoji = young ? '🧒' : old ? '🧓' : '🧑';

  // タグ候補: [ラベル, 強さ(=50からの距離)]。強い順に最大4つ。
  const cands: [string, number][] = [];
  const push = (cond: boolean, label: string, strength: number) => {
    if (cond) cands.push([label, strength]);
  };
  push(gender >= 58, '女性', gender - 50);
  push(gender <= 42, '男性', 50 - gender);
  push(v(s, 'warmth') >= 60, 'フレンドリー', v(s, 'warmth') - 50);
  push(v(s, 'warmth') <= 40, 'クール', 50 - v(s, 'warmth'));
  push(old, '落ち着いた', age - 50);
  push(young, '若々しい', 50 - age);
  push(v(s, 'pitch') >= 64, '高め', v(s, 'pitch') - 50);
  push(v(s, 'pitch') <= 36, '低め', 50 - v(s, 'pitch'));
  push(v(s, 'huskiness') >= 60, 'ハスキー', v(s, 'huskiness') - 50);
  push(v(s, 'clarity') >= 62, 'クリア', v(s, 'clarity') - 50);
  push(v(s, 'clarity') <= 38, 'こもり', 50 - v(s, 'clarity'));
  push(v(s, 'roughness') >= 60, 'ガラガラ', v(s, 'roughness') - 50);
  push(v(s, 'build') >= 64, '細い声', v(s, 'build') - 50);
  push(v(s, 'build') <= 36, '太い声', 50 - v(s, 'build'));

  cands.sort((a, b) => b[1] - a[1]);
  let tags = cands.slice(0, 4).map((c) => c[0]);
  if (tags.length === 0) tags = ['ニュートラル'];
  return { emoji, tags };
}

/** 2 つのスライダー設定の類似度(0..100%)。共通軸のユークリッド距離ベース。 */
export function similarity(a: Sliders, b: Sliders, keys: string[]): number {
  const ks = keys.filter((k) => a[k] !== undefined && b[k] !== undefined);
  if (ks.length === 0) return 0;
  let sse = 0;
  for (const k of ks) {
    const d = (a[k] ?? 50) - (b[k] ?? 50);
    sse += d * d;
  }
  const dist = Math.sqrt(sse / ks.length); // 0..100
  return Math.max(0, Math.round(100 - dist));
}

/** 現在のスライダーに最も近いアンカーの類似度(0..100)。 */
export function bestMatch(
  s: Sliders,
  anchors: { name: string; sliders: Sliders }[],
  keys: string[],
): { name: string; score: number } | null {
  let best: { name: string; score: number } | null = null;
  for (const a of anchors) {
    const sc = similarity(s, a.sliders, keys);
    if (!best || sc > best.score) best = { name: a.name, score: sc };
  }
  return best;
}

// --- 共有リンク（スライダーを URL に符号化） ---------------------------------
export function encodeSliders(s: Sliders, axes: Axis[]): string {
  const o: Record<string, number> = {};
  axes.forEach((a) => (o[a.key] = Math.round(s[a.key] ?? 50)));
  return encodeURIComponent(btoa(JSON.stringify(o)));
}

export function decodeSliders(param: string): Sliders | null {
  try {
    const o = JSON.parse(atob(decodeURIComponent(param)));
    if (!o || typeof o !== 'object') return null;
    const out: Sliders = {};
    for (const [k, v] of Object.entries(o)) {
      const n = Number(v);
      if (Number.isFinite(n)) out[k] = Math.min(100, Math.max(0, Math.round(n))); // 0..100 にクランプ
    }
    return Object.keys(out).length ? out : null;
  } catch {
    return null;
  }
}
