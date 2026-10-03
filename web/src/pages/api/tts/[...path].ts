// BFF: テキスト読み上げ（VOICEVOX ENGINE）。読み上げた音声を「変換元」に使う。
//   GET  /api/tts/speakers   → 話者（キャラクター×スタイル）の一覧。VOICEVOX が無ければ 503
//   POST /api/tts/synthesize → { text, speaker, speed?, pitch?, intonation? } → { wav_b64, credit }
// VOICEVOX は同梱しない。利用者が自分の PC で起動しておく（既定 http://127.0.0.1:50021）。
// 生成した音声を使うときは「VOICEVOX:キャラクター名」のクレジット表記が必要（各キャラクターの規約に従う）。
import fs from 'fs';
import type { NextApiRequest, NextApiResponse } from 'next';

const API_ENV = 'VOICEVOX_URL';   // 実行時 env（動的キー参照でビルド時のインライン展開を避ける）
const base = () => (process.env[API_ENV] || 'http://127.0.0.1:50021').replace(/\/$/, '');
const MAX_CHARS = 300;

export const config = { api: { bodyParser: { sizeLimit: '1mb' }, responseLimit: '30mb' } };

interface VvSpeaker { name: string; styles: { name: string; id: number }[] }

async function vv(path: string, init?: RequestInit, timeoutMs = 60_000): Promise<Response> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    return await fetch(`${base()}${path}`, { ...init, signal: ctl.signal });
  } finally {
    clearTimeout(t);
  }
}

// Web サーバーが WSL の中で動いているか。WSL の既定（NAT）では、Windows で起動した VOICEVOX に
// 127.0.0.1 では届かないので、画面に WSL 向けの案内を出す
let wslCache: boolean | null = null;
function inWsl(): boolean {
  if (wslCache === null) {
    try { wslCache = /microsoft/i.test(fs.readFileSync('/proc/version', 'utf8')); } catch { wslCache = false; }
  }
  return wslCache;
}

// つながらなかった理由を、利用者に分かる言葉にする（AbortError はこちらのタイムアウトで打ち切ったもの）
function reason(e: unknown): string {
  const t = String(e);
  if (/AbortError|aborted/i.test(t)) return '応答がありませんでした';
  if (/ECONNREFUSED|fetch failed/i.test(t)) return '接続を受け付けていません';
  return t;
}

const unavailable = (res: NextApiResponse, e: unknown) =>
  res.status(503).json({ error: `VOICEVOXに接続できません（${reason(e)}）。VOICEVOXを起動してください`, wsl: inWsl() });

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const action = ((req.query.path as string[]) || []).join('/');

  if (req.method === 'GET' && action === 'speakers') {
    try {
      const r = await vv('/speakers', undefined, 5_000);
      if (!r.ok) return unavailable(res, `HTTP ${r.status}`);
      const list = (await r.json()) as VvSpeaker[];
      return res.json(list.flatMap((s) => s.styles.map((st) => ({ id: st.id, name: s.name, style: st.name }))));
    } catch (e) {
      return unavailable(res, e);
    }
  }

  if (req.method === 'POST' && action === 'synthesize') {
    const { text, speaker, speed, pitch, intonation } = req.body ?? {};
    const t = String(text ?? '').trim();
    if (!t) return res.status(400).json({ error: '読み上げるテキストを入力してください' });
    if (t.length > MAX_CHARS) return res.status(400).json({ error: `テキストは${MAX_CHARS}文字までです` });
    if (!Number.isInteger(speaker)) return res.status(400).json({ error: '話者を選んでください' });
    try {
      const q = await vv(`/audio_query?text=${encodeURIComponent(t)}&speaker=${speaker}`, { method: 'POST' });
      if (!q.ok) return res.status(502).json({ error: `読み方の解析に失敗しました（HTTP ${q.status}）` });
      const query = await q.json();
      // 話す速さ・高さ・抑揚（VOICEVOX の単位）。変換後もテンポと抑揚はこれに従う
      if (typeof speed === 'number') query.speedScale = Math.min(2, Math.max(0.5, speed));
      if (typeof pitch === 'number') query.pitchScale = Math.min(0.15, Math.max(-0.15, pitch));
      if (typeof intonation === 'number') query.intonationScale = Math.min(2, Math.max(0, intonation));
      const s = await vv(`/synthesis?speaker=${speaker}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(query),
      }, 120_000);
      if (!s.ok) return res.status(502).json({ error: `読み上げに失敗しました（HTTP ${s.status}）` });
      const wav = Buffer.from(await s.arrayBuffer());
      // クレジット用のキャラクター名
      let credit = 'VOICEVOX';
      try {
        const list = (await (await vv('/speakers', undefined, 5_000)).json()) as VvSpeaker[];
        const hit = list.find((x) => x.styles.some((st) => st.id === speaker));
        if (hit) credit = `VOICEVOX:${hit.name}`;
      } catch { /* 名前が取れなくても読み上げ自体は返す */ }
      return res.json({ wav_b64: `data:audio/wav;base64,${wav.toString('base64')}`, credit });
    } catch (e) {
      return unavailable(res, e);
    }
  }

  return res.status(404).json({ error: 'not found' });
}
