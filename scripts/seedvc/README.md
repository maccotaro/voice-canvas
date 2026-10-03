# Seed-VC 統合スクリプト（中間声生成）

最終出力VCエンジンは **Seed-VC**（github.com/Plachtaa/seed-vc）。本ディレクトリの
スクリプトは Seed-VC リポジトリを `external/seed-vc/`（.gitignore対象）に clone した上で、
その中にコピーして実行する（`from inference import ...` がリポジトリ内 import に依存するため）。

## セットアップ
1. `git clone https://github.com/Plachtaa/seed-vc external/seed-vc`
2. 専用venv `.venv-seedvc`（torch==2.4.0 / transformers==4.46.3 / numpy==1.26.4 等）
3. 本スクリプトを `external/seed-vc/` にコピー

device は `voice_canva/seedvc_device.py` が決めて Seed-VC に渡す（`VOICE_CANVA_DEVICE` を優先、無ければ cuda、それも無ければ cpu。
MPS は autocast 非対応のため使わない）。`external/seed-vc/inference.py` を書き換える必要はない。

## 実行（cwd=external/seed-vc）
```
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=. ../../.venv-seedvc/bin/python -u vc_concatblend.py
```

## 中間声の作り方（検証で確定）
2話者の参照から「実在しない中間声」を**クリーン**に作る方式:
- `vc_concatblend.py`: 2話者の参照を割合可変で**連結**→1回生成。純粋な端点に到達するが中間制御が非線形。
- `vc_emblerp.py`: campplus話者埋め込みを**線形補間**＋両声連結プロンプト。中間制御が滑らか（端点は純粋話者にならない）。
両方ともユーザー承認済み（クリーン・実用）。

却下した方式: style2補間のみ(弱い), 出力mel線形補間(F0櫛干渉で掠れる)。
