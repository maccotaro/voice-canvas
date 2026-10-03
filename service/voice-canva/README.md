# 声のCanva 推論サービス

意味軸スライダー → Seed-VC 生成を行う推論マイクロサービス。
Docker コンテナ + FastAPI で動く単体サービスとして、任意のバックエンドから呼び出せる。

## 構成
| ファイル | 役割 |
|---|---|
| `server.py` | FastAPI。`/health` `/axes` `/anchors` `/generate` `/analyze` `/anchors/*` |
| `canva_service.py` | コア。Seed-VC モデルロード＋意味軸デザイン(voice_canva.design)＋生成 |
| `requirements.txt` | 依存（torch2.4 / Seed-VC系 / pyworld・parselmouth / FastAPI） |
| `Dockerfile` | CUDA ベース。Seed-VC を clone、資産は volume |
| `docker-compose-voice-canva.yml` | 単体起動用の compose |

## 起動手順
1. アンカー資産を作る（リポジトリ直下の README「アンカーを作る」参照）
2. リポジトリ資産を `voice-canva-assets` ボリュームへ置く（`voice_canva/` パッケージ、
   `data/anchor_embeddings.npz`、`data/spk*.wav`、`data/tgt_*_long.wav`、`features/*.npz`）。
   既定キャリアは `VOICE_CANVA_CARRIER` で指定する（未指定時は `data/spk2.wav`）
3. `docker compose -f docker-compose-voice-canva.yml up -d voice-canva`
4. フロントからは `http://voice-canva:8770` をプロキシして呼ぶ（web/ の BFF プロキシを参照）

⚠️ Docker イメージには Seed-VC（GPL-3.0）が含まれる。イメージを配布する場合は GPL-3.0 の条件に従うこと。

## API
| メソッド | パス | 内容 |
|---|---|---|
| GET | `/health` | 起動状態・軸・アンカー数・device |
| GET | `/axes` | 8軸定義（key/label/low/high/status） |
| GET | `/anchors` | アンカー一覧（名前＋各軸スライダー値） |
| GET | `/anchor_audio/{name}` | アンカー試聴wav |
| POST | `/analyze` | `{audio_b64}` → `{sliders}` 録音解析 |
| POST | `/generate` | `{sliders, carrier_b64?}` → `{wav_b64, top}` |
| GET | `/anchors/admin` | アンカー一覧（品質・素材名・スライダー値）、退避済み一覧、`ready`（3 人以上か） |
| POST | `/anchors/uploads` | `{audio_b64, filename}` → 取り込みを受け付け（裏で 1 本ずつ選定・品質チェック） |
| GET | `/anchors/uploads` | 取り込みの状況（順番待ち／処理中／採用／不採用と理由） |
| POST | `/anchors/uploads/clear` | 終わった取り込みを一覧から消す |
| POST | `/anchors/{name}/exclude` | アンカーを外す（ファイルは `_excluded/` へ退避） |
| POST | `/anchors/{name}/restore` | 外したアンカーを戻す |
| POST | `/anchors/{name}/delete` | 自分で追加したアンカーを完全に削除する（同梱のアンカーは 400） |
| GET | `/sample_source` | 同梱の変換元音声（画面の「サンプル音声」） |
| POST | `/tools/separate` | `{audio_b64, filename?}` → 素材ツールの「BGM・雑音の除去」を受け付け（Demucs、裏で 1 本ずつ） |
| GET | `/tools/separate/{id}` | 進み具合（経過秒・見込み秒・処理前後の録音品質） |
| GET | `/tools/separate/{id}/audio` | 声だけにした WAV |

アンカーの追加は `/anchors/uploads` だけ（15 秒以上・1 人の声・録音品質の確認を通ったものだけ採用する）。

アンカーが 3 人未満のとき、`/generate` と `/analyze` は 409 と理由を返す。

## ローカル検証（GPU不要・CPU可）
```
VOICE_CANVA_PROJ=<repo> VOICE_CANVA_DEVICE=cpu HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=<seed-vc-dir>:<repo> \
  uvicorn server:app --host 127.0.0.1 --port 8770
curl http://127.0.0.1:8770/health
```
（注: MPS は Seed-VC の autocast 非対応のため Mac ローカルは CPU 推奨）
