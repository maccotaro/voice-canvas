#!/usr/bin/env bash
# 声のCanva 推論サービスを「44.1kHz F0条件付きモデル」で起動する。
# 22.05kHz版より広帯域(本物の高域)だが、モデルが大きくCPUでは生成が遅い(GPU推奨)。
#
# 初回は 44k モデル一式(DiT/rmvpe/bigvgan_44k)を Hugging Face から自動取得する。
# 取得が途中で止まる環境では scripts/seedvc/hf_curl_fetch.py で先に取得しておく。
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export VOICE_CANVA_F0="${VOICE_CANVA_F0:-1}"                 # 44k F0条件付きモデルを使う
export VOICE_CANVA_OUTPUT_SR="${VOICE_CANVA_OUTPUT_SR:-44100}"  # 出力も44.1kHz(ダウンサンプルしない)
export VOICE_CANVA_AUTO_F0="${VOICE_CANVA_AUTO_F0:-1}"       # キャリアF0を目標音域へ寄せる
# キャッシュ済み前提だが、hf_hub は HEAD 確認にオンラインが要る(大ファイルは再DLされない)
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-0}"

echo "▶ 44.1kHz(F0)モードで起動します（初回はモデルDLが必要。CPUでは生成が遅い）"
exec bash "$PROJ/scripts/start-backend.sh"
