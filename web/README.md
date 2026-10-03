# Voice Canvas Web（Next.js）

声のデザイン（`/`）・アンカー管理（`/anchors`）・素材ツール（`/tools`）・使い方（`/manual`）の画面。
推論サービス（`service/voice-canva/`）と VOICEVOX へは、このアプリの API ルート（`src/pages/api/`）が中継する。

- 起動とビルド: リポジトリ直下の [README](../README.md)
- 構成とコードの置き場所: [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md)
- 使い方（マニュアル）: [public/manual/manual.md](public/manual/manual.md)（アプリでは右上の「使い方」）

```bash
cp .env.example .env    # CANVA_API_URL（推論サービスの URL）
npm install
npm run dev             # http://localhost:3010
npm run build && npm start
npm run type-check
```
