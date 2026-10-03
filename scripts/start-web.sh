#!/usr/bin/env bash
# 声のCanva フロント(Next.js)をローカル起動する。
# 推論サービス(start-backend.sh)を先に起動しておくこと。
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ/web"

# .env 用意（CANVA_API_URL）
[ -f .env ] || { cp .env.example .env 2>/dev/null || true; }

# 依存
[ -d node_modules ] || { echo "▶ npm install ..."; npm install; }

echo "▶ 声のCanva フロント起動 → http://localhost:3010"
echo "  （推論サービスが http://127.0.0.1:8770 で起動済みであること）"
exec npm run dev
