# Voice Canvas（声のCanva）

**声のデザインを、もっと自由に。** Voice Canvas は、8 つの特徴をスライダーで調整して声を作る、誰でも無料で使えるオープンソースのアプリです（MIT ライセンス、β版）。元の音声を用意すると、話す内容・テンポ・抑揚を保ったまま、Seed-VC で声質を変換します。同梱の実在の話者の声「アンカー」69 人分から、設定に近い声を最大 4 人まで混ぜて目標の声を作ります。GPU がなくても動作します。

操作のダイジェスト（3分・音声つき）

https://github.com/user-attachments/assets/59b6f903-ef3f-4dd0-a3cb-ecec8068ce6b

## できること

- VOICEVOX による読み上げ、マイク録音、音声ファイル、同梱サンプルから元の音声を用意する。
- 年齢感・性別・声の高さ・体格・ハスキー度・明瞭度・温かさ・粗さの 8 つの特徴で声を設定する。
- 変換した声をテイクごとに聴き比べ、話すスピードやピッチの揺らぎを仕上げて WAV で保存する。
- 声の設定を JSON や共有リンクで保存・共有する。
- アンカーを追加・整理して、作れる声の幅を広げる。
- 素材ツールで音声の抽出、BGM・雑音の除去、カット、ピッチ・テンポの調整、結合、録音を行う。

## 動作環境

- Python 3.10
- Node.js 20 以上（npm）
- git
- Mac・Linux と、Windows 11 の WSL2（Ubuntu 22.04）で動作を確認しています。Windows で使うときは、下の「Windows（WSL2）で使う」を見てください。PowerShell など Windows のネイティブ環境では、この README の手順どおりには動きません。
- GPU は不要です。NVIDIA GPU があれば使用します。
- 初回にモデル約 3.2GB を自動取得します。BGM・雑音の除去を使うと、Demucs 約 80MB を追加取得します。

CPU では、変換 1 回に 1〜数分かかります。この開発環境（8 コアの CPU、22.05kHz の標準モデル）では、約 2.5 秒の文の変換に 1 本あたり約 70 秒かかりました。

## インストールと起動（クイックスタート）

```bash
git clone <このリポジトリ> voice-canvas && cd voice-canvas

# 1. 推論サービス（Seed-VC）の準備
git clone https://github.com/Plachtaa/seed-vc external/seed-vc
python3.10 -m venv .venv-seedvc
.venv-seedvc/bin/pip install -r service/voice-canva/requirements.txt

# 2. 推論サービスを起動（初回はモデル約3.2GBを自動取得。http://127.0.0.1:8770/health で確認）
bash scripts/start-backend.sh            # 22.05kHz モデル（軽い）
# bash scripts/start-backend-44k.sh      # 44.1kHz モデル（高音質・重い。GPU 推奨）

# 3. 別のターミナルで Web を起動 → http://localhost:3010
bash scripts/start-web.sh
```

初回起動時に、同梱アンカー 69 人分が `anchors/default/` から `data/` へ展開され、そのまま使える状態になります。

### 更新するとき

`git pull` のあと、依存が増えていれば次を実行し、推論サービスと Web を再起動してください。

```bash
.venv-seedvc/bin/pip install -r service/voice-canva/requirements.txt
cd web && npm install
```

### Web の本番ビルド

```bash
cd web && npm run build && npm start
```

ポートは 3010 です。

### 環境変数

Web の設定例は [`web/.env.example`](web/.env.example) にあります。

| Web の環境変数 | 用途 | 既定値・指定方法 |
|---|---|---|
| `CANVA_API_URL` | 推論サービスの URL | `http://127.0.0.1:8770` |
| `VOICEVOX_URL` | VOICEVOX の URL | `http://127.0.0.1:50021` |
| `NEXT_BASE_PATH` | サブパスでの配信 | ビルド時に指定 |

| 推論サービスの環境変数 | 用途 | 既定値・指定方法 |
|---|---|---|
| `VOICE_CANVA_DEVICE` | 使用するデバイス（`cuda` / `cpu`） | CUDA があれば `cuda`、なければ `cpu` |
| `PORT` | ポート番号 | `8770` |
| `HF_HUB_OFFLINE` | モデル取得後のオフライン動作 | モデル取得後に `1` にすると起動が速くなります |

## 使い方

操作の流れや各機能の説明は、アプリ右上の「使い方」から開けます。GitHub では[利用者向けマニュアル](web/public/manual/manual.md)を読んでください。

## VOICEVOX との連携

文章から元の音声を作る場合は、[VOICEVOX 公式サイト](https://voicevox.hiroshiba.jp/)から各自でインストールし、起動しておいてください。VOICEVOX は同梱していません。

VOICEVOX を起動すると自動で接続します。読み上げを使うあいだは、VOICEVOX を開いたままにしてください。

別の PC や別のポートで VOICEVOX を動かす場合は、Web の環境変数 `VOICEVOX_URL` に接続先を指定します。既定値は `http://127.0.0.1:50021` です。
Web を Docker で動かすときは、Mac・Windows とも `http://host.docker.internal:50021` を指定します。

## Windows（WSL2）で使う

Windows では、WSL2 の Ubuntu の中で動かします。起動スクリプトが bash で書かれていて、venv の場所も Linux・Mac の形（`.venv-seedvc/bin/python`）を前提にしているためです。
Windows 11 と WSL2（Ubuntu 22.04）で動作を確認しています。

### 1. WSL（Ubuntu）に入れておくもの

```bash
sudo apt update
sudo apt install -y git build-essential python3.10-venv python3.10-dev
```

- `python3.10-venv` は venv を作るのに必要です。
- `build-essential` と `python3.10-dev` は pyworld のビルドに必要です。pyworld には Python 3.10 向けの配布済みパッケージがなく、インストール時にソースからビルドされます。
- Node.js 20 以上は、WSL の中に Linux 版を入れます（nvm など）。Windows 側の Node（nvm4w など）が PATH に混ざって見えることがあるので、`which node` が WSL 内のパスを指しているか確かめてください。

このあとは「インストールと起動」と同じ手順です。

### 2. VOICEVOX につなぐ

Windows 版の VOICEVOX は、Windows の `127.0.0.1:50021` でだけ待ち受けます。WSL の既定のネットワーク（NAT）では、WSL の中で動く Web サーバーから `127.0.0.1` で Windows に届かないため、VOICEVOX が見つかりません。画面の案内にも、WSL で動いているときはその旨が出ます。
次のどれか1つで解決します。

1. **WSL をミラーモードにする**（いちばん簡単で、コードの変更はいりません）。Windows の `%USERPROFILE%\.wslconfig` に次を書き、PowerShell で `wsl --shutdown` を実行してから WSL を開き直します。`wsl --shutdown` を実行すると、WSL の中で動いている作業（起動中のサーバーやターミナルの作業など）もすべて止まるので、先に保存しておいてください。

   ```ini
   [wsl2]
   networkingMode=mirrored
   ```

2. VOICEVOX のエンジンを `--host 0.0.0.0` で起動し、Web の環境変数 `VOICEVOX_URL` に Windows 側の IP アドレスを指定します（例 `http://172.19.128.1:50021`）。この IP アドレスは WSL の既定ゲートウェイで、WSL の中で `ip route | awk '/default/ {print $3}'` を実行すると分かります。Windows のファイアウォールで許可が必要な場合があります。
3. WSL の中で VOICEVOX のエンジンを動かします（Linux 版、または Docker の `voicevox/voicevox_engine`）。

### 3. GPU（NVIDIA）を使う

WSL の GPU は、Windows 側の NVIDIA ドライバーで動きます。WSL の中にドライバーは入れません。
推論サービスの torch 2.4.0 は CUDA 12.1 向けなので、Windows の NVIDIA ドライバーを CUDA 12.1 以上に対応する版に更新してください。
古いドライバー（例 522.06。CUDA 11.8 まで対応）では「NVIDIA driver on your system is too old」と表示され、CPU で動きます。

## Docker で動かす

推論サービスには、CUDA ベースの [`service/voice-canva/Dockerfile`](service/voice-canva/Dockerfile) があります。
イメージには Seed-VC と推論サービスのコードだけを入れ、このリポジトリ（`voice_canva/`・同梱アンカー・`data/`）は `/assets/voice-canva` にマウントします。リポジトリ直下で次を実行します。

```bash
docker build -t voice-canva service/voice-canva
docker run --gpus all -p 8770:8770 -v "$PWD":/assets/voice-canva voice-canva
```

Web には [`web/Dockerfile`](web/Dockerfile) があります。次は `/canva` で配信するビルド例です。

```bash
docker build --build-arg NEXT_BASE_PATH=/canva -t voice-canva-web web/
docker run -p 3000:3000 -e CANVA_API_URL=http://voice-canva:8770 voice-canva-web
```

Compose 用の設定は [`service/voice-canva/docker-compose-voice-canva.yml`](service/voice-canva/docker-compose-voice-canva.yml) にあります。

推論サービスのイメージは Seed-VC を含みます。**イメージを配布する場合は GPL-3.0 に従ってください。**

## 音声素材とライセンス

- **本リポジトリのコード**: MIT License（[`LICENSE`](LICENSE)）。
- **Seed-VC**（[Plachtaa/seed-vc](https://github.com/Plachtaa/seed-vc)）: **GPL-3.0**。本リポジトリには同梱せず、実行時に import します。`service/voice-canva/Dockerfile` で作るイメージは Seed-VC を含むため、**イメージを配布する場合は GPL-3.0 に従ってください**。
- **アンカー音声**: [Common Voice](https://commonvoice.mozilla.org/) 日本語（Mozilla Data Collective 配布、**CC0-1.0**）から作っています。`anchors/default/` に Common Voice 45 人分を同梱しています。内容は 12 秒の参照音声・話者ベクトル・声の高さなどの統計値です。詳細は同フォルダの [`LICENSE.md`](anchors/default/LICENSE.md) を参照してください。声を再合成できる分析データ（F0・スペクトル包絡など）は同梱・保存しません。Common Voice のダウンロード時には「**データセット内の話者の身元を特定しない**」ことに同意します。話者の特定につながる用途には使わないでください。
- **試聴音声** `web/public/personas/*.wav`: 同梱アンカー（Common Voice と JVNV）で合成したものです。読み上げ文のキャリアも Common Voice（`common_voice_ja_39002059.mp3`、アンカーとは別の話者）です。
- **感情アンカー**: [JVNV](https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus)（日本語感情音声コーパス、**CC BY-SA 4.0**）の 4 人 × 6 感情 = 24 人分を同梱しています（`jvnv_*`）。高めの声や感情のこもった声の幅を広げます。出典の表示が必要です。これらを改変・再配布するときは、同じ CC BY-SA 4.0 で配布してください。JVNV のアンカーを混ぜて作った試聴音声も含みます。同梱アンカーは合計約 27MB です。
- **ほかの音声合成キャラクターの声（VOICEVOX・つくよみちゃんコーパスなど）**: 同梱していません。キャラクターごとに利用規約（クレジット表記、音声変換や「素材」としての利用の可否）が異なります。使う場合は各規約を確認し、各自でアンカー管理から追加してください。
- **任意の高品質アンカー（JVS コーパス）**: 研究・非商用・個人利用に限り利用でき、**再配布はできません**。使う場合は各自で入手し、同梱・公開しないでください。
- **モデル重み**: リポジトリには含めません。初回実行時に Hugging Face などから自動取得します。以下は 2026-09-29 に各配布元で確認した内容です（Demucs は表内の日付）。

| モデル | 用途 | ライセンス |
|---|---|---|
| `Plachta/Seed-VC`（DiT チェックポイント） | 声質変換の本体 | **GPL-3.0** |
| `funasr/campplus`（campplus_cn_common.bin） | 話者埋め込み | Apache-2.0 |
| `lj1995/VoiceConversionWebUI`（rmvpe） | F0（音の高さ）推定 | MIT |
| `nvidia/bigvgan_v2_22khz_80band_256x` / `nvidia/bigvgan_v2_44khz_128band_512x` | ボコーダ | MIT |
| `openai/whisper-small` | 発話内容の特徴抽出 | Apache-2.0 |
| torchaudio `SQUIM_OBJECTIVE`（アンカー選定の品質ゲートのみ） | 録音品質の推定 | CC BY 4.0（DNS 2020 で学習） |
| Demucs `htdemucs`（素材ツールの BGM・雑音の除去のみ。初回に dl.fbaipublicfiles.com から取得） | 声と伴奏の分離 | MIT（Demucs リポジトリのライセンス。重みに別の表記なし。2026-10-03 確認） |

いずれも、商用・非商用を問わず使えるライセンスです。重みを同梱・再配布する場合は、各ライセンスの表記義務に従ってください。CC BY 4.0 は出典表示、GPL-3.0 はソース提供が必要です。

## 開発者向け

構成・API・アンカーの作り方・テスト・研究用の旧コードについては、[開発者向けドキュメント](docs/DEVELOPMENT.md)を参照してください。
