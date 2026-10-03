// BFFプロキシ: フロント /api/canva/* → 推論サービス(FastAPI) へ転送。
// コンテナで動かすときは CANVA_API_URL をサービス名(例 http://voice-canva:8770)に。
//
// 44kHzモデルのCPU生成は数分〜数十分かかり得る。グローバル fetch(undici)は既定タイムアウト
// (≈300秒)で 502 になり、かつ undici を直接 import できないため、Node標準の http/https で
// プロキシしてタイムアウトを撤廃する（接続確立は30sで打ち切り、応答待ちは無制限）。
import type { NextApiRequest, NextApiResponse } from 'next';
import http from 'http';
import https from 'https';
import { URL } from 'url';

// CANVA_API_URL は「実行時」の環境変数(deployment の env)から読む。
// 注意: Next.js は `process.env.CANVA_API_URL`(ドット記法)をビルド時にバンドルへ
// インライン展開する(webpack DefinePlugin)。そのままだとビルド時の値(既定 ARG の
// 127.0.0.1)が焼き込まれ、実行時 env が無視されて 502(ECONNREFUSED)になる。
// 動的キー参照(`process.env[VAR]`)は DefinePlugin の置換対象外なので実行時 env が読める。
const API_ENV = 'CANVA_API_URL';
const apiBase = () => process.env[API_ENV] || 'http://127.0.0.1:8770';

export const config = {
  api: {
    bodyParser: { sizeLimit: '30mb' },
    responseLimit: '25mb',
    externalResolver: true, // 長時間処理でNextの応答監視警告を抑止
  },
};

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  return new Promise<void>((resolve) => {
    const API = apiBase();
    const parts = (req.query.path as string[]) || [];
    const u = new URL(`${API}/${parts.join('/')}`);
    const mod = u.protocol === 'https:' ? https : http;
    const isBodyless = req.method === 'GET' || req.method === 'HEAD';
    const body = isBodyless ? undefined : Buffer.from(JSON.stringify(req.body ?? {}));

    const preq = mod.request(
      {
        hostname: u.hostname,
        port: u.port || (u.protocol === 'https:' ? 443 : 80),
        path: u.pathname + u.search,
        method: req.method,
        headers: {
          'Content-Type': 'application/json',
          ...(body ? { 'Content-Length': body.length } : {}),
        },
      },
      (pres) => {
        const chunks: Buffer[] = [];
        pres.on('data', (c) => chunks.push(c as Buffer));
        pres.on('end', () => {
          const buf = Buffer.concat(chunks);
          res.setHeader('Content-Type', pres.headers['content-type'] || 'application/json');
          res.status(pres.statusCode || 200).send(buf);
          resolve();
        });
      },
    );
    // 応答待ちは無制限（長時間生成対応）。接続確立のみ30秒で打ち切る。
    preq.setTimeout(0);
    preq.on('socket', (s) => {
      s.setTimeout(30_000, () => {
        if (!s.destroyed && (s.connecting || !s.writable)) s.destroy(new Error('connect timeout'));
      });
      s.once('connect', () => s.setTimeout(0));
    });
    preq.on('error', (e) => {
      if (!res.headersSent) res.status(502).json({ error: `voice-canva API unreachable: ${String(e)}` });
      resolve();
    });
    if (body) preq.write(body);
    preq.end();
  });
}
