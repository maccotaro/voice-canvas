"""声のCanva (Voice Designer) — Gradio UI（memo Step 4）。

6 本の意味づけ軸スライダー（config.AXES）で声をデザインし、
スライダー変更で即時プレビュー（WORLD 即時合成）、確定後に
reference.wav として書き出す。重い依存（gradio 等）は関数内 import。
"""
from __future__ import annotations

import glob
import os
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:  # 型のみ。実行時に重い依存を読み込まない。
    import gradio as gr

    from .analysis import SpeakerFeatures
    from .axes import AxisRanges


def build_demo(base: "SpeakerFeatures", ranges: "AxisRanges") -> "gr.Blocks":
    """ベース話者と軸可動域から Gradio Blocks を構築する。

    config.AXES をループして 6 本の gr.Slider を生成し、スライダー変更
    （change）で synthesis.synthesize を即時プレビューに流す。明示の
    「再生」ボタンと、reference.wav 書き出しボタンも用意する。

    Args:
        base: ベース話者の特徴量（SP/AP 構造の土台）。
        ranges: 各軸の物理可動域（±2σ ベース）。

    Returns:
        gr.Blocks インスタンス（未 launch）。
    """
    import gradio as gr

    from . import io_utils, synthesis

    def _render(*values: float) -> tuple[int, "object"]:
        """スライダー値群から波形を合成し gr.Audio 用タプルを返す。"""
        axis_values = {key: float(v) for key, v in zip(config.AXIS_KEYS, values)}
        wav = synthesis.synthesize(axis_values, base, ranges)
        return (base.sr, wav)

    def _export(*values: float) -> str:
        """現在のスライダー値で合成し reference.wav を書き出す。"""
        axis_values = {key: float(v) for key, v in zip(config.AXIS_KEYS, values)}
        wav = synthesis.synthesize(axis_values, base, ranges)
        path = io_utils.export_reference(wav, base.sr)
        return f"書き出しました: `{os.path.abspath(path)}`"

    with gr.Blocks(title="声のCanva (Voice Designer)") as demo:
        gr.Markdown(
            f"# 声のCanva (Voice Designer)\n"
            f"ベース話者: **{base.name}** ／ サンプルレート: {base.sr} Hz\n\n"
            "各スライダーを動かすと、裏で複数の WORLD パラメータが相関連動し、"
            "即時に試聴できます。確定した声は reference.wav として書き出せます。"
        )

        sliders: list["gr.Slider"] = []
        for axis in config.AXES:
            slider = gr.Slider(
                minimum=config.AXIS_MIN,
                maximum=config.AXIS_MAX,
                value=0.0,
                step=0.05,
                label=axis.label,
                info=f"左:{axis.low} ⇄ 右:{axis.high} — {axis.description}",
            )
            sliders.append(slider)

        audio = gr.Audio(label="プレビュー", type="numpy", autoplay=True)

        with gr.Row():
            play_btn = gr.Button("再生", variant="primary")
            export_btn = gr.Button("reference.wav として書き出し")

        export_info = gr.Markdown()

        # スライダー変更で即時プレビュー。
        for slider in sliders:
            slider.change(_render, inputs=sliders, outputs=audio)

        # 明示の再生ボタン。
        play_btn.click(_render, inputs=sliders, outputs=audio)

        # 書き出し。
        export_btn.click(_export, inputs=sliders, outputs=export_info)

        # 起動直後にベース話者そのまま（全軸 0.0）を一度合成して提示。
        demo.load(_render, inputs=sliders, outputs=audio)

    return demo


def main() -> None:
    """features_dir の最初の話者を読み込み、UI を起動する。

    config.PATHS.features_dir 内の最初の .npz を SpeakerFeatures.load で
    読み込み、axes.compute_ranges で可動域を算出して build_demo→launch する。
    特徴量が見つからない場合は分かりやすいメッセージを表示して終了する。
    """
    from .analysis import SpeakerFeatures
    from .axes import compute_ranges

    features_dir = config.PATHS.features_dir
    npz_paths = sorted(glob.glob(os.path.join(features_dir, "*.npz")))
    if not npz_paths:
        print(
            "特徴量が見つかりません。\n"
            f"  探索先: {os.path.abspath(features_dir)}\n"
            "  先に `python -m voice_canva.analysis` 等で data/ の wav を分析し、\n"
            "  features/ に *.npz を書き出してください（memo Step 1）。"
        )
        return

    features = [SpeakerFeatures.load(p) for p in npz_paths]
    base = features[0]
    ranges = compute_ranges(features)

    demo = build_demo(base, ranges)
    demo.launch()


if __name__ == "__main__":
    main()
