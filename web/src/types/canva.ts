// 声のCanva 型定義

export interface Axis {
  key: string;
  label: string;
  low: string;
  high: string;
  status: 'measured' | 'approx' | 'needs_label';
}

export type Sliders = Record<string, number>; // key -> 0..100

export interface Anchor {
  name: string;
  sliders: Sliders;
}

export interface TopAnchor {
  name: string;
  weight: number;
}

export interface GenerateResult {
  wav_b64: string;
  sr: number;
  top: TopAnchor[];
  take_id: number; // 仕上げ（postprocess）でこのテイクを指す番号
}

export interface AdvParams {
  speed: number; // 話すスピード 0.5..2.0（x）
  pitchVar: number; // ピッチの揺らぎ 0..100（%）
  breath: number; // 息遣いの強さ 0..100（%）
}

// ---- アンカー管理 ----
export interface AnchorItem {
  name: string;
  kind: 'base' | 'user'; // base=品質チェックを通したアンカー / user=詳細設定から1本追加したもの
  source: string; // 素材のファイル名
  quality: number | null; // 録音品質（PESQ 推定。基準 2.3）
  single: number | null; // 単一話者スコア（基準 0.55）
  added: string | null;
  f0: number; // 声の高さの中央値 [Hz]
  sliders: Sliders;
  bundled: boolean; // 同梱パックのアンカー（外せるが削除はできない）
  warnings: string[]; // 追加したときの注意（録音品質が低め など）
}

export interface ExcludedAnchor {
  name: string;
  kind: 'base' | 'user';
  source: string;
  bundled: boolean;
}

export interface AnchorOverview {
  anchors: AnchorItem[];
  excluded: ExcludedAnchor[];
  min_anchors: number;
  ready: boolean;
  pending: number;
}

export interface UploadJob {
  id: string;
  filename: string;
  status: 'queued' | 'processing' | 'accepted' | 'rejected' | 'error';
  step: string;
  sec: number;
  name?: string;
  reason?: string;
  metrics?: { quality: number; single: number | null; f0: number; at: number };
  warnings?: string[]; // 採用したが基準に届かなかったところ（注意として見せる）
}

// 素材ツール「BGM・雑音の除去」の処理（サーバーで1本ずつ）
export interface SeparateJob {
  id: string;
  filename: string;
  status: 'queued' | 'processing' | 'done' | 'error';
  step: string;
  sec: number;
  elapsed?: number; // 処理を始めてからの秒
  estimate: number; // 見込みの秒
  quality_before: number | null; // 録音品質（アンカー登録と同じ尺度。目安 2.3）
  quality_after: number | null;
  reason?: string;
}
