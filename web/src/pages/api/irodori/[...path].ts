// BFFプロキシ: フロント /api/irodori/* → Irodori-TTS-Server(OpenAI互換) へ転送。
// canva プロキシ([...path].ts)と同型。応答は WAV バイナリのためバッファ中継。
// 対象URLは「実行時」env IRODORI_API_URL(動的キー参照でビルド時インライン展開を回避)。
import type { NextApiRequest, NextApiResponse } from 'next';
import http from 'http';
import https from 'https';
import { URL } from 'url';

const API_ENV = 'IRODORI_API_URL';
const apiBase = () => process.env[API_ENV] || 'http://irodori-tts-server:8088';

export const config = {
  api: {
    bodyParser: { sizeLimit: '25mb' },
    responseLimit: '25mb',
    externalResolver: true, // 初回はモデルDL+ロードで数分かかるため応答監視警告を抑止
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
    // 応答待ちは無制限(初回モデルロード対応)。接続確立のみ30秒で打ち切る。
    preq.setTimeout(0);
    preq.on('socket', (s) => {
      s.setTimeout(30_000, () => {
        if (!s.destroyed && (s.connecting || !s.writable)) s.destroy(new Error('connect timeout'));
      });
      s.once('connect', () => s.setTimeout(0));
    });
    preq.on('error', (e) => {
      if (!res.headersSent) res.status(502).json({ error: `irodori-tts-server unreachable: ${String(e)}` });
      resolve();
    });
    if (body) preq.write(body);
    preq.end();
  });
}
