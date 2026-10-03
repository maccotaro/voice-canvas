// 声のCanva APIクライアント（フロント → BFFプロキシ /api/canva/* → FastAPI）
import type {
  Axis, Anchor, Sliders, GenerateResult, AdvParams, AnchorOverview, UploadJob, SeparateJob,
} from '@/types/canva';

// basePath 配信時（NEXT_PUBLIC_BASE_PATH=/canva 等）はプレフィックスを付与
const BASE = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/api/canva`;

// サーバーが {detail} で返す理由（「アンカーが足りません」等）をそのまま画面に出す
async function fail(r: Response, label: string): Promise<never> {
  let msg = `${label} failed: ${r.status}`;
  try {
    const j = await r.json();
    if (typeof j?.detail === 'string') msg = j.detail;
    else if (typeof j?.error === 'string') msg = j.error;
  } catch { /* JSON でない応答は既定文言 */ }
  throw new Error(msg);
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}/${path}`);
  if (!r.ok) return fail(r, `GET ${path}`);
  return r.json();
}
async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) return fail(r, `POST ${path}`);
  return r.json();
}

export const canvaApi = {
  axes: () => jget<Axis[]>('axes'),
  anchors: () => jget<Anchor[]>('anchors'),
  anchorAudioUrl: (name: string) => `${BASE}/anchor_audio/${encodeURIComponent(name)}`,
  analyze: (audio_b64: string) => jpost<{ sliders: Sliders }>('analyze', { audio_b64 }),
  generate: (sliders: Sliders, carrier_b64?: string | null, adv?: AdvParams, faithful?: boolean) =>
    jpost<GenerateResult>('generate', {
      sliders,
      carrier_b64: carrier_b64 ?? null,
      // バックエンドの命名(スネークケース)に合わせて送る
      speed: adv?.speed,
      pitch_variation: adv?.pitchVar,
      breathiness: adv?.breath,
      // 学習素材用の忠実モード(AUTO_F0 off/steps多め/DSP off)
      faithful: faithful ?? false,
    }),
  // ---- アンカー管理 ----
  anchorsAdmin: () => jget<AnchorOverview>('anchors/admin'),
  uploads: () => jget<UploadJob[]>('anchors/uploads'),
  upload: (audio_b64: string, filename: string) =>
    jpost<UploadJob>('anchors/uploads', { audio_b64, filename }),
  clearUploads: () => jpost<UploadJob[]>('anchors/uploads/clear', {}),
  excludeAnchor: (name: string) => jpost<AnchorOverview>(`anchors/${encodeURIComponent(name)}/exclude`, {}),
  restoreAnchor: (name: string) => jpost<AnchorOverview>(`anchors/${encodeURIComponent(name)}/restore`, {}),
  // 自分で足したアンカーだけ完全に削除できる（同梱のアンカーはサーバーが断る）
  deleteAnchor: (name: string) => jpost<AnchorOverview>(`anchors/${encodeURIComponent(name)}/delete`, {}),
  // 素材ツール: BGM・雑音を除いて声だけを残す（裏で処理。進み具合を取りに行く）
  separate: (audio_b64: string, filename: string) => jpost<SeparateJob>('tools/separate', { audio_b64, filename }),
  separateStatus: (id: string) => jget<SeparateJob>(`tools/separate/${id}`),
  separateAudioUrl: (id: string) => `${BASE}/tools/separate/${id}/audio`,
  // テイクに後処理のみ再適用（再生成なし・即時）
  postprocess: (adv: AdvParams, takeId?: number) =>
    jpost<{ wav_b64: string; sr: number }>('postprocess', {
      speed: adv.speed, pitch_variation: adv.pitchVar, breathiness: adv.breath, take_id: takeId ?? null,
    }),
};
