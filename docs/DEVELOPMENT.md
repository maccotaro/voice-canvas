# Voice Canvas 開発者向けガイド

Voice Canvas の現在のアプリは、Next.js の Web と FastAPI の推論サービスで構成されています。声質の変換には Seed-VC を使い、8 つの特徴の設定に近いアンカーを最大 4 人まで混ぜて、目標の声を作ります。

インストールと起動、本番ビルド、環境変数、Docker の設定は [README](../README.md) を参照してください。構成図は [architecture.html](architecture.html) にあります。

## Web の構成

`web/` は Next.js 15（Pages Router）、TypeScript、Tailwind、zustand を使っています。

### ページと API の中継

以下のパスは `web/` からの相対パスです。

| パス | 役割 |
|---|---|
| `src/pages/index.tsx` | 声のデザイン |
| `src/pages/anchors.tsx` | アンカー管理 |
| `src/pages/tools.tsx` | 素材ツール |
| `src/pages/manual.tsx` | マニュアル表示 |
| `src/pages/api/canva/[...path].ts` | 推論サービスへの中継 |
| `src/pages/api/tts/[...path].ts` | VOICEVOX への中継 |
| `src/pages/api/irodori/...` | Irodori-TTS 関連の API |

VOICEVOX は同梱していません。Web からの接続先は `VOICEVOX_URL` で指定し、既定値は `http://127.0.0.1:50021` です。推論サービスへの接続先は `CANVA_API_URL` で指定し、既定値は `http://127.0.0.1:8770` です。

### コンポーネントと共有処理

声のデザインのコンポーネントは `src/components/canva/` にあります。元の音声を扱う `SourcePanel`、声を設定する `DesignPanel`、変換結果を扱う `TakesPanel` のほか、`RadarChart`、`SampleVoices`、`ExtrasPanel`、`BatchConvert`、`IrodoriPanel`、`parts` が含まれます。

アンカー管理のコンポーネントは `src/components/anchors/`、素材ツールのコンポーネントは `src/components/tools/` にあります。

状態管理は `src/stores/` の `canvaStore` と `toolsStore` が担当します。共有処理は `src/lib/` にあり、`canvaApi`、`audioTools`、`audioPrep`、`wavRecorder`、`axisMeta`、`voice` を含みます。

### マニュアルと章へのリンク

利用者向けマニュアルの本文は [web/public/manual/manual.md](../web/public/manual/manual.md) です。アプリの `/manual` と GitHub の両方で読むため、画像は本文から `img/<名前>.webp` の相対パスで参照します。

章の見出しの直前に `<a id="..."></a>` を置き、章へのリンク先を指定します。アンカー管理の「使い方」は `/manual#anchors`、素材ツールの「使い方」は `/manual#tools` に直接移動します。

## 推論サービスと API

`service/voice-canva/` は FastAPI による推論サービスです。

| ファイル | 役割 |
|---|---|
| `server.py` | API のエンドポイント |
| `canva_service.py` | Seed-VC による声の変換と解析 |
| `anchor_admin.py` | アンカーの取り込み、一覧、外す・戻す・削除の処理 |
| `material_tools.py` | Demucs による素材ツールの BGM 除去 |

API の一覧は [service/voice-canva/README.md](../service/voice-canva/README.md) を参照してください。

`scripts/start-backend.sh` は、これらのファイルを `external/seed-vc` に置いて起動します。Seed-VC の `inference.py` と同じ階層に置く必要があるためです。

## Python パッケージとデータ

### 現在のアプリで使う処理

`voice_canva/` に、声の設計やアンカーを扱う Python の処理があります。

| ファイル | 役割 |
|---|---|
| `design.py` | 8 軸の定義、アンカーバンク、スライダーの値から重みへの変換、上位 4 人の混合 |
| `anchor_select.py` | アンカーに使う区間の選定と確認。CLI とサービスで共用 |
| `default_anchors.py` | 同梱アンカーパックの展開 |
| `seedvc_device.py` | Seed-VC の実行デバイスに関する処理 |
| `analysis.py` | 録音から声の高さ・フォルマントなどの音響の統計値を測る（アンカーの取り込み・録音の解析で使う。定数は `config.py`） |

アンカーの取り込みでは、8 秒未満の音声と、話し声が見つからない音声を不採用にします。落ち着いて話している区間は自動で選びます。1 人だけの声かどうかの目安は 0.55、録音品質の目安は 2.3 です。これらに届かない場合も採用し、「注意」を付けます。

### 同梱アンカーと実行時のデータ

`anchors/default/` は同梱アンカーパックです。音声の FLAC、話者ベクトル、manifest、`LICENSE.md` を含みます。Common Voice 日本語 45 人分と JVNV 感情音声 24 人分の、合計 69 人分を同梱しています。

初回起動時に `anchors/default/` から `data/` へ展開され、同梱アンカーを使える状態になります。`data/`、`features/`、`output/` は実行時に作られ、git の管理対象には含まれません。

素材やモデルのライセンスは [README の「音声素材とライセンス」](../README.md#音声素材とライセンス) と [同梱パックの LICENSE.md](../anchors/default/LICENSE.md) を参照してください。

### スクリプト

`scripts/` には、素材の準備、同梱パックの作成、試聴音声の生成、起動に使うスクリプトがあります。

| スクリプト | 用途 |
|---|---|
| `cv_prepare.py`、`seedvc/select_anchors.py`、`build_default_anchors.py` | Common Voice / JVNV からのアンカーパック作成 |
| `gen_persona_samples.py` | 「こんな声が作れます」の音声生成 |
| `gen_persona_avatars.py` | 顔アイコンの生成 |
| `start-*.sh` | 各サービスの起動 |

## アンカーを作る（Common Voice 日本語）

`scripts/cv_prepare.py` の冒頭に手順がある。概要:

1. Mozilla Data Collective から Common Voice 日本語を入手し、`validated.tsv` などの表だけを展開する
2. `python scripts/cv_prepare.py select <cv-corpus-*/ja> --out work/` — 性別×年代の12枠から各6人を候補にする
3. `tar -xzf <アーカイブ> -T work/clips.txt` — 必要なクリップだけを展開する
4. `python scripts/cv_prepare.py concat <cv-corpus-*/ja> --out work/` — 話者ごとに1本の wav にする
5. `scripts/seedvc/select_anchors.py work/speakers --start-index 1 > work/select.log` — 落ち着いた区間の選定と品質ゲート
6. `python scripts/cv_prepare.py pick work/select.log --per-bucket 3` — 枠ごとに品質上位3人（計36人）を残す
7. `scripts/seedvc/precompute_anchors.py` — 話者埋め込みを計算する

参考: 2026-09 に Common Voice 27.0 で作った 36 話者のアンカーは、CPU（8スレッド）で選定に約3時間かかった。

その後、年配の声を増やすために 50 代・60 代以上の枠から 9 人（`cv_*`）を、感情の幅を広げるために JVNV の 24 人（`jvnv_*`）を加え、
`scripts/build_default_anchors.py` で同梱パック（`anchors/default/`）にまとめている。既存のアンカー名は変えずに追加する。

## テスト

`tests/` にモデル不要の単体テストがあります（`test_axes.py` と `test_config.py` は旧コードのテスト）。

```bash
python -m pytest tests
```

## 研究用の旧コード

初期の MVP は、WORLD ボコーダを使い、6 軸のスライダーから音声を直接合成する構成でした。次のファイルは、その頃のものです。

- `voice_canva/app.py`：Gradio UI
- `voice_canva/axes.py`
- `voice_canva/synthesis.py`
- `voice_canva/io_utils.py`、`voice_canva/morph.py`
- `scripts/step0_analysis_resynth.py`
- ルートの `requirements.txt` と `pyproject.toml`

現在のアプリ（Web と推論サービス）は、この旧コードを使っていません。現在の推論サービスの依存関係は `service/voice-canva/requirements.txt` を使って準備します。

当時の設計メモは [docs/legacy/memo.md](legacy/memo.md) と [docs/legacy/INTERFACES.md](legacy/INTERFACES.md) に移しています。パラメータは独立には動かせないこと、軸は解釈しやすさを優先して人手で設計すること、ガードレールは UI で吸収することという設計思想は、現在の 8 軸設計にも引き継いでいます。