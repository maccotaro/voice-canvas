"""Seed-VC を動かす device の決定（サービスと scripts/seedvc で共用）。

Seed-VC の inference.py はモジュール読み込み時に cuda > mps > cpu の順で device を決め、
load_models や推論関数はそのモジュール変数 `inference.device` を参照する。
MPS は autocast に対応していないため、Mac でそのまま動かすと失敗する。
外部リポジトリを書き換えずに済むよう、ここで device を決めて `inference.device` に反映する。
"""
from __future__ import annotations

import os


def select_device():
    """環境変数 VOICE_CANVA_DEVICE（"cuda"/"cpu"）を優先し、無ければ cuda、それも無ければ cpu。"""
    import torch

    d = os.environ.get("VOICE_CANVA_DEVICE")
    if d:
        return torch.device(d)
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def configure_seedvc_device():
    """device を決めて Seed-VC の `inference.device` に反映し、その device を返す。

    load_models より前に呼ぶこと（モデルの配置先がこの値で決まる）。
    """
    import inference  # Seed-VC（cwd=external/seed-vc 前提）

    dev = select_device()
    inference.device = dev
    return dev
