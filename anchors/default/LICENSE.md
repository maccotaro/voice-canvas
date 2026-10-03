# 同梱アンカーの出典とライセンス

同梱のアンカーは 2 つのコーパスから作っています。**アンカーごとにライセンスが異なります**（`manifest.json` の `dataset`）。

| dataset | コーパス | ライセンス | アンカー |
|---|---|---|---|
| `cv` | Common Voice 日本語 27.0（Mozilla Data Collective 配布） | **CC0-1.0**（パブリックドメイン） | `spk1`〜`spk36` と `cv_<性別><年代>_<番号>` の 9 人（計 45 人） |
| `jvnv` | JVNV（日本語感情音声コーパス） | **CC BY-SA 4.0** | `jvnv_<話者>_<感情>` の 24 人 |

## Common Voice（`spk1`〜`spk36`・`cv_*`）

- 性別（女性・男性）× 年代（10代〜60代以上）の 12 枠から、録音品質の高い順に各 3 人（`spk1`〜`spk36`）
- 年配の声を増やすため、50代・60代以上の枠から 9 人を追加（`cv_f50_*`・`cv_f60_*`・`cv_m50_*`・`cv_m60_*`）
- 各アンカーは、その話者のクリップをつないだ録音から、落ち着いて話している 12 秒を選んだもの
- `carrier.flac`（既定の変換元音声）も Common Voice の 1 クリップ（アンカーとは別の話者）

Common Voice の配布元では、ダウンロード時に「**データセット内の話者の身元を特定しない**」ことへの同意が求められています。
この音声も同じ趣旨で扱い、話者を特定しようとしないでください。

## JVNV（`jvnv_*`）

- 話者 4 人（女性 A・B = F1・F2、男性 A・B = M1・M2）× 6 感情（喜び・悲しみ・怒り・恐れ・嫌悪・驚き）
- 各アンカーは、その話者・感情の台本発話（regular）から笑い・泣きなどの非言語区間を除いてつなぎ、落ち着いた 12 秒を選んだもの
- **CC BY-SA 4.0**: 出典の表示が必要です。また、これらのアンカー音声を改変・再配布するときは同じ CC BY-SA 4.0 で配布してください。
  JVNV のアンカーを混ぜて作った音声（`web/public/personas/` の試聴音声を含む）も、この条件に従うものとして扱ってください。

出典: Detai Xin, Junfeng Jiang, Shinnosuke Takamichi, Yuki Saito, Akiko Aizawa, and Hiroshi Saruwatari.
"JVNV: A Corpus of Japanese Emotional Speech with Verbal Content and Nonverbal Expressions." arXiv:2310.06072, 2023.
https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus

## 共通

- `embeddings.npz`: 上の音声から計算した話者ベクトル
- `manifest.json`: 表示用ラベル・品質の記録・音響の統計値（声の高さの平均など）。声を再合成できる分析データは含めていない

## 作り直す

`scripts/cv_prepare.py`（Common Voice の素材選定）、`scripts/seedvc/select_anchors.py`（区間の選定）、
`scripts/build_default_anchors.py`（このパックの組み立て）で再現できます。手順は `docs/DEVELOPMENT.md` の「アンカーを作る」を参照してください。
