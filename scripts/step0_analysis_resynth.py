"""声のCanva — memo Step 0「分析再合成の地盤確認」単体検証 CLI。

memo §4 Step 0 / §6(1)(2) の地盤を、外部依存なしに 1 コマンドで確認するための
スクリプト。指定 wav を pyworld で分析（:func:`analysis.analyze_wav`）し、

1. そのまま再合成（:func:`synthesis.resynthesize`）して原音相当に戻るかを確認、
2. さらに F0 を ±N 半音（既定 ±2）スケーリングした 2 版を書き出し、
   破綻せず自然に聞こえるか（memo §6(2)）を耳で確認する、

ための wav を ``output/`` 以下に保存する。

F0 スケーリングは生 WORLD パラメータを直接いじらず、ベース特徴の F0 のみを
半音スケールした :class:`SpeakerFeatures` を作り、同じ再合成エンジン
（:func:`synthesis.resynthesize`）に通して実現する（変換則の重複定義を避ける）。

使い方
------
リポジトリルートで実行する::

    python scripts/step0_analysis_resynth.py path/to/voice.wav

オプション::

    python scripts/step0_analysis_resynth.py path/to/voice.wav \
        --name speaker01 --out-dir output --semitones 2.0

出力（``--out-dir`` 既定は config.PATHS.output_dir = "output"）::

    <stem>_resynth.wav        # 無加工の分析再合成（原音相当の確認）
    <stem>_f0_up<+N>st.wav    # F0 を +N 半音
    <stem>_f0_down<-N>st.wav  # F0 を -N 半音

実行には pyworld / librosa / soundfile が必要（関数内 import）。これらが無い環境
でも本ファイルの import 自体はクラッシュしない。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

import numpy as np

# リポジトリルートを import パスに追加（どの cwd から呼ばれても voice_canva を解決）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from voice_canva import analysis, config, io_utils, synthesis  # noqa: E402
from voice_canva.analysis import SpeakerFeatures  # noqa: E402


def _scale_f0_semitones(base: SpeakerFeatures, semitones: float) -> SpeakerFeatures:
    """ベース特徴の有声 F0 を ``semitones`` 半音だけスケールした複製を返す。

    無声フレーム（F0=0）は 0 のまま保持する。SP/AP・スカラ統計は据え置き
    （Step 0 は F0 シフト単独の破綻有無を耳で確かめる検証のため）。

    Args:
        base: 元の話者特徴。
        semitones: 半音シフト量（正で上昇、負で下降）。

    Returns:
        F0 のみをスケールした新しい :class:`SpeakerFeatures`。
    """
    factor = 2.0 ** (float(semitones) / 12.0)
    f0 = np.array(base.f0, dtype=np.float64, copy=True)
    voiced = f0 > 0.0
    f0[voiced] *= factor
    return replace(base, f0=f0)


def _build_parser() -> argparse.ArgumentParser:
    """CLI 引数パーサを構築する。"""
    p = argparse.ArgumentParser(
        prog="step0_analysis_resynth",
        description="memo Step 0: 分析再合成 + F0 ±N 半音版の書き出し（地盤確認）",
    )
    p.add_argument("wav", help="入力 wav のパス（クリーンな単一話者録音）")
    p.add_argument(
        "--name",
        default=None,
        help="話者 ID（省略時はファイル名から自動）",
    )
    p.add_argument(
        "--out-dir",
        default=config.PATHS.output_dir,
        help=f"出力ディレクトリ（既定: {config.PATHS.output_dir}）",
    )
    p.add_argument(
        "--semitones",
        type=float,
        default=2.0,
        help="F0 スケーリングの半音幅（既定: 2.0 → ±2 半音版を書き出し）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。書き出した wav パスを標準出力に表示する。

    Args:
        argv: 引数リスト（None で sys.argv を使用）。

    Returns:
        終了コード（0=成功）。
    """
    args = _build_parser().parse_args(argv)

    in_path = os.path.abspath(args.wav)
    if not os.path.isfile(in_path):
        print(f"[error] 入力 wav が見つかりません: {in_path}", file=sys.stderr)
        return 2

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(in_path))[0]
    semi = float(args.semitones)

    # 1) 分析（pyworld + parselmouth）。
    print(f"[step0] analyze: {in_path}")
    feats = analysis.analyze_wav(in_path, name=args.name)
    print(
        f"[step0] frames={feats.f0.shape[0]} sr={feats.sr} "
        f"f0_mean={feats.f0_mean:.1f}Hz f0_std={feats.f0_std:.1f}"
    )

    # 2) 無加工の分析再合成（原音相当の確認）。
    wav_resynth = synthesis.resynthesize(feats)
    p_resynth = os.path.join(out_dir, f"{stem}_resynth.wav")
    io_utils.save_wav(p_resynth, wav_resynth, feats.sr)

    # 3) F0 ±N 半音版（破綻しないことの耳確認）。
    feats_up = _scale_f0_semitones(feats, +semi)
    feats_down = _scale_f0_semitones(feats, -semi)
    wav_up = synthesis.resynthesize(feats_up)
    wav_down = synthesis.resynthesize(feats_down)
    p_up = os.path.join(out_dir, f"{stem}_f0_up{semi:+.0f}st.wav")
    p_down = os.path.join(out_dir, f"{stem}_f0_down{-semi:+.0f}st.wav")
    io_utils.save_wav(p_up, wav_up, feats.sr)
    io_utils.save_wav(p_down, wav_down, feats.sr)

    print("[step0] wrote:")
    for path in (p_resynth, p_up, p_down):
        print(f"  {os.path.abspath(path)}")
    print("[step0] done — 各 wav を試聴し、原音相当復元 / ±半音で破綻しないことを確認。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
