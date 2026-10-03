// 声のCanva 状態管理（zustand）。元の音声・スライダー値・テイク（聴き比べ）・メモリなど。
import { create } from 'zustand';
import type { Axis, Anchor, Sliders, AdvParams } from '@/types/canva';
import { canvaApi } from '@/lib/api/canvaApi';

export interface MemoryPreset {
  name: string;
  sliders: Sliders;
}

// 元の音声の用意のしかた: 文章を VOICEVOX で読み上げ / その場で録音 / 音声ファイル
export type SourceKind = 'tts' | 'rec' | 'file';

export interface Source {
  kind: SourceKind;
  b64: string;
  label: string; // 受け皿に出す名前（話者名・ファイル名など）
  credit: string | null; // VOICEVOX の読み上げのときのクレジット（例 "VOICEVOX:ずんだもん"）
}

// 変換してできた1本。仕上げ（話速・揺らぎ）はテイクごとにサーバーの素波形へ掛け直す
export interface Take {
  id: number; // サーバーの take_id
  no: number; // 画面に出す番号（テイク1, 2, …）
  wav: string;
  sliders: Sliders;
  adv: AdvParams;
  credit: string | null;
}

// 既定はDSPオフ（素の生成忠実度を優先）。ユーザーが上げたときのみ効果適用。
const DEFAULT_ADV: AdvParams = { speed: 1.0, pitchVar: 0, breath: 0 };

const LS_KEY = 'voice-canva.memory';

function loadMemory(): MemoryPreset[] {
  if (typeof window === 'undefined') return [];
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || '[]');
  } catch {
    return [];
  }
}
function saveMemory(m: MemoryPreset[]) {
  if (typeof window !== 'undefined') localStorage.setItem(LS_KEY, JSON.stringify(m));
}

interface CanvaState {
  axes: Axis[];
  anchors: Anchor[];
  sliders: Sliders;
  source: Source | null;
  generating: boolean;
  genStartedAt: number | null;
  genError: string | null;
  takes: Take[]; // 新しい順
  currentTake: number | null; // 選んでいるテイクの id
  adv: AdvParams;
  memory: MemoryPreset[];

  setAxes: (a: Axis[]) => void;
  setAnchors: (a: Anchor[]) => void;
  setSlider: (key: string, value: number) => void;
  setSliders: (s: Sliders) => void;
  setSource: (s: Source | null) => void;
  generate: () => Promise<void>;
  randomize: () => void;
  selectTake: (id: number) => void;
  setAdv: (p: Partial<AdvParams>) => void;
  applyAdv: () => Promise<void>;
  downloadTake: () => void;
  saveMemoryPreset: (name: string) => void;
  recallMemory: (name: string) => void;
}

export const useCanvaStore = create<CanvaState>((set, get) => ({
  axes: [],
  anchors: [],
  sliders: {},
  source: null,
  generating: false,
  genStartedAt: null,
  genError: null,
  takes: [],
  currentTake: null,
  adv: DEFAULT_ADV,
  memory: loadMemory(),

  setAxes: (axes) => {
    // 軸が来たら未設定スライダーを50で初期化
    const sliders = { ...get().sliders };
    axes.forEach((a) => {
      if (sliders[a.key] === undefined) sliders[a.key] = 50;
    });
    set({ axes, sliders });
  },
  setAnchors: (anchors) => set({ anchors }),
  setSlider: (key, value) => set({ sliders: { ...get().sliders, [key]: value } }),
  setSliders: (s) => set({ sliders: { ...get().sliders, ...s } }),
  setSource: (source) => set({ source }),

  generate: async () => {
    const { sliders, source, adv, takes } = get();
    // 元の音声が無いと変換できない（画面でもボタンを押せないようにしている）
    if (!source) return;
    set({ generating: true, genStartedAt: Date.now(), genError: null });
    try {
      const r = await canvaApi.generate(sliders, source.b64, adv);
      const take: Take = {
        id: r.take_id, no: (takes[0]?.no ?? 0) + 1, wav: r.wav_b64,
        sliders: { ...sliders }, adv: { ...adv }, credit: source.credit,
      };
      set({ takes: [take, ...get().takes], currentTake: take.id });
    } catch (e) {
      set({ genError: e instanceof Error ? e.message : String(e) });
    } finally {
      set({ generating: false, genStartedAt: null });
    }
  },
  randomize: () => {
    const sliders = { ...get().sliders };
    get().axes.forEach((a) => (sliders[a.key] = Math.round(Math.random() * 100)));
    set({ sliders });
  },
  selectTake: (id) => {
    const t = get().takes.find((x) => x.id === id);
    if (t) set({ currentTake: id, adv: { ...t.adv } });
  },
  setAdv: (p) => set({ adv: { ...get().adv, ...p } }),
  applyAdv: async () => {
    // 選んでいるテイクに後処理だけ掛け直す（再生成しないので同じ音声で差を確かめられる）
    const { currentTake, adv } = get();
    if (currentTake == null) return;
    try {
      const r = await canvaApi.postprocess(adv, currentTake);
      set({
        takes: get().takes.map((t) => (t.id === currentTake ? { ...t, wav: r.wav_b64, adv: { ...adv } } : t)),
      });
    } catch (e) {
      set({ genError: e instanceof Error ? e.message : String(e) });
    }
  },
  downloadTake: () => {
    const t = get().takes.find((x) => x.id === get().currentTake);
    if (!t) return;
    const a = document.createElement('a');
    a.href = t.wav;
    a.download = `voice-canvas-take${t.no}.wav`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  },

  saveMemoryPreset: (name) => {
    const nm = name.trim() || `メモリ${get().memory.length + 1}`;
    const memory = [...get().memory.filter((m) => m.name !== nm), { name: nm, sliders: { ...get().sliders } }];
    saveMemory(memory);
    set({ memory });
  },
  recallMemory: (name) => {
    const m = get().memory.find((x) => x.name === name);
    if (m) set({ sliders: { ...get().sliders, ...m.sliders } });
  },
}));
