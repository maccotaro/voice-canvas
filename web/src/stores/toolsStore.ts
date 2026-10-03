// 素材ツールの素材トレイ（できた音声の置き場）。ページを移っても残す（再読み込みで消える）。
import { create } from 'zustand';
import type { SeparateJob } from '@/types/canva';

export type ToolKey = 'extract' | 'separate' | 'cut' | 'pitch' | 'join' | 'record';

export interface Clip {
  id: string;
  name: string;
  b64: string; // WAV の data URI（busy の間は空）
  sec: number;
  color: string; // 作ったツールの色
  trail: string[]; // 通ってきたツール（例 ["動画", "抽出", "BGM除去"]）
  state: 'ready' | 'busy' | 'error';
  error?: string;
  sentToAnchor?: boolean;
}

// BGM除去のジョブ（裏で進む。できたら clipId のトレイ項目に入れる）
export interface SepWatch { job: SeparateJob; clipId: string; inputId: string }

interface ToolsState {
  sep: SepWatch[]; // 新しい順
  tool: ToolKey;
  inputId: string | null; // いま開いているツールの入力
  handoff: string | null; // トレイの「ツールに回す」で渡された素材（結合はこれを最初に入れておく）
  clips: Clip[]; // 新しい順
  setTool: (t: ToolKey, inputId?: string | null) => void;
  setInput: (id: string | null) => void;
  add: (c: Omit<Clip, 'id'>) => string;
  update: (id: string, p: Partial<Clip>) => void;
  remove: (id: string) => void;
  addSep: (w: SepWatch) => void;
  updateSep: (job: SeparateJob) => void;
}

let seq = 0;
export const useToolsStore = create<ToolsState>((set, get) => ({
  tool: 'extract',
  inputId: null,
  handoff: null,
  clips: [],
  sep: [],
  setTool: (tool, inputId) => set({ tool, handoff: inputId ?? null, ...(inputId !== undefined ? { inputId } : {}) }),
  setInput: (inputId) => set({ inputId }),
  add: (c) => {
    const id = `c${Date.now().toString(36)}${(seq++).toString(36)}`;
    set({ clips: [{ ...c, id }, ...get().clips] });
    return id;
  },
  update: (id, p) => set({ clips: get().clips.map((x) => (x.id === id ? { ...x, ...p } : x)) }),
  addSep: (w) => set({ sep: [w, ...get().sep] }),
  updateSep: (job) => set({ sep: get().sep.map((w) => (w.job.id === job.id ? { ...w, job } : w)) }),
  remove: (id) => set({ clips: get().clips.filter((x) => x.id !== id), inputId: get().inputId === id ? null : get().inputId }),
}));
