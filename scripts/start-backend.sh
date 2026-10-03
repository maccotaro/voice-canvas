#!/usr/bin/env bash
# 声のCanva 推論サービス(FastAPI)をローカル起動する。
# service/voice-canva/ のサービスコード(*.py)を Seed-VC(external/seed-vc)に配置して uvicorn 実行。
# （Seed-VC の inference.py と同階層が必要なため）
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEEDVC="$PROJ/external/seed-vc"
VENV="$PROJ/.venv-seedvc"
PORT="${PORT:-8770}"
# 使う装置。指定しなければ、NVIDIA GPU（CUDA）が使えれば cuda、使えなければ cpu（Mac の MPS は使わない）。
DEVICE="${VOICE_CANVA_DEVICE:-auto}"

# 事前チェック
[ -d "$SEEDVC" ]        || { echo "❌ Seed-VC が見つかりません: $SEEDVC (git clone https://github.com/Plachtaa/seed-vc external/seed-vc)"; exit 1; }
[ -x "$VENV/bin/python" ] || { echo "❌ venv python が見つかりません: $VENV (.venv-seedvc を作成し依存導入してください)"; exit 1; }
[ -f "$PROJ/data/anchor_embeddings.npz" ] || echo "ℹ️  アンカーが未登録です。起動後に画面の「アンカー管理」から登録してください"

# サービスコードを Seed-VC 配下へ配置
cp "$PROJ"/service/voice-canva/*.py "$SEEDVC/"

cd "$SEEDVC"
export VOICE_CANVA_PROJ="$PROJ"
[ "$DEVICE" = auto ] || export VOICE_CANVA_DEVICE="$DEVICE"
# 初回はモデル(約3.2GB)を Hugging Face から取得するためオンラインが必要。取得後は 1 にすると速い
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-0}"
export PYTHONPATH=".:$PROJ"

echo "▶ 声のCanva 推論サービス起動 (device=$DEVICE port=$PORT)"
echo "  http://127.0.0.1:$PORT/health  で確認。Ctrl+C で停止。"
exec "$VENV/bin/python" -m uvicorn server:app --host 127.0.0.1 --port "$PORT"
