/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 開発モード（npm run dev / start-web.sh）でも画面の隅に Next.js のマークを出さない
  devIndicators: false,
  // k8s 等でコンテナ配信するための standalone 出力
  output: 'standalone',
  // サブパス配信（例: 親アプリの /canva 配下）。ビルド時に指定。
  basePath: process.env.NEXT_BASE_PATH || '',
  // バックエンド推論サービス(FastAPI)のURL。BFFプロキシ(pages/api/canva)が参照。
  env: { CANVA_API_URL: process.env.CANVA_API_URL || 'http://127.0.0.1:8770' },
  // 埋め込み元のページが COEP: credentialless を送る場合、その iframe に
  // 埋め込まれるには本アプリ側も COEP を宣言する必要がある(未宣言だとブラウザが
  // フレームをブロックし「接続が拒否されました」になる)。アセットは同一オリジン
  // のみなので credentialless で副作用なし。
  async headers() {
    return [
      {
        // '/:path*' は basePath ルート(/canva そのもの)にもマッチする('/(.*)' は不一致)
        source: '/:path*',
        headers: [
          { key: 'Cross-Origin-Embedder-Policy', value: 'credentialless' },
          { key: 'Cross-Origin-Resource-Policy', value: 'same-site' },
        ],
      },
    ];
  },
};
module.exports = nextConfig;
