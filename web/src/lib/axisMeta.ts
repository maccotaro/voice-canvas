// 各意味軸のデザイン要素（色・アイコン）。デザインモックのカラフルな軸表現に合わせる。
import {
  Hourglass, Users, AudioLines, Ruler, Wind, MessageCircle, Heart, Waves, type LucideIcon,
} from 'lucide-react';

export interface AxisMeta {
  color: string;
  Icon: LucideIcon;
}

// 現行8軸（age/gender/pitch/build/huskiness/clarity/warmth/roughness）に色とアイコンを割当。
export const AXIS_META: Record<string, AxisMeta> = {
  age: { color: '#a78bfa', Icon: Hourglass },
  gender: { color: '#e879f9', Icon: Users },
  pitch: { color: '#60a5fa', Icon: AudioLines },
  build: { color: '#38bdf8', Icon: Ruler },
  huskiness: { color: '#fb923c', Icon: Wind },
  clarity: { color: '#34d399', Icon: MessageCircle },
  warmth: { color: '#fb7185', Icon: Heart },
  roughness: { color: '#2dd4bf', Icon: Waves },
};

export const axisMeta = (key: string): AxisMeta =>
  AXIS_META[key] ?? { color: '#7c5cff', Icon: AudioLines };
