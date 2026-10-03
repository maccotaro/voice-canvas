# 声のCanva 推論サービス（Seed-VC + 意味軸デザイン）
# 推論コンテナ。CUDA ベース。CPU 運用時は python ベースイメージに差し替え可。
#
# Build（リポジトリ直下で）: docker build -t voice-canva service/voice-canva
# Run:   docker run --gpus all -p 8770:8770 -v "$PWD":/assets/voice-canva voice-canva
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
ENV HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0
ENV VOICE_CANVA_PROJ=/assets/voice-canva
ENV VOICE_CANVA_DEVICE=cuda

# python は Ubuntu 22.04 標準の 3.10 に統一（pip/uvicorn が 3.10 を使うため、
# 3.11 を混在させると拡張ビルドが 3.10 ヘッダを見つけられず失敗する）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-dev python3-venv python3-pip build-essential git ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*
RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /opt/voice-canva

# Seed-VC 本体（推論コード）。inference.py を PYTHONPATH に載せる。
RUN git clone --depth 1 https://github.com/Plachtaa/seed-vc /opt/seed-vc
ENV PYTHONPATH=/opt/seed-vc:/assets/voice-canva

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip "setuptools<81" wheel \
 && pip install --no-cache-dir -r requirements.txt

# サービスコード（server / canva_service / anchor_admin / material_tools）
COPY *.py ./

# /assets/voice-canva に voice_canva パッケージ・data(anchor_embeddings/tgt_*)・features を
# ボリュームでマウントする（モデル/アンカー資産はイメージに焼かず外出し）。
# 例: -v /path/to/voice-canva-repo:/assets/voice-canva
EXPOSE 8770
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8770"]
