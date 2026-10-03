"""音声入出力ユーティリティ。

INTERFACES.md の io_utils 契約を実装する。
重い依存（librosa / soundfile）は未インストール環境でも import 時にクラッシュ
しないよう、すべて関数内 import とする。
波形は内部で float32・[-1, 1] にクリップして扱う。
"""
from __future__ import annotations

import os

import numpy as np

from . import config


def _to_float32_clipped(wav: np.ndarray) -> np.ndarray:
    """波形を float32 / [-1, 1] に正規化（クリップ）して返す。

    Args:
        wav: 任意 dtype・任意形状の波形配列。

    Returns:
        float32 で値域 [-1, 1] にクリップした 1 次元波形。
    """
    arr = np.asarray(wav, dtype=np.float32)
    # 多チャンネルが渡された場合は平均してモノラル化する。
    if arr.ndim > 1:
        arr = arr.mean(axis=tuple(range(1, arr.ndim)))
    arr = np.ascontiguousarray(arr, dtype=np.float32)
    return np.clip(arr, -1.0, 1.0)


def load_wav(path: str, sr: int = config.DEFAULT_SR) -> tuple[np.ndarray, int]:
    """wav を読み込み、指定サンプルレートのモノラル float32 波形にして返す。

    librosa で `sr` にリサンプルし、モノラル化する。波形は [-1, 1] にクリップする。

    Args:
        path: 入力 wav のパス。
        sr: 出力サンプルレート（既定 config.DEFAULT_SR）。

    Returns:
        (波形 float32 [-1,1] (T,), サンプルレート sr) のタプル。
    """
    import librosa  # 関数内 import（重い依存）

    wav, out_sr = librosa.load(path, sr=sr, mono=True)
    return _to_float32_clipped(wav), int(out_sr)


def save_wav(path: str, wav: np.ndarray, sr: int) -> None:
    """波形を wav ファイルとして書き出す。

    親ディレクトリが存在しなければ作成する。波形は float32 / [-1, 1] にクリップして
    から書き出す。

    Args:
        path: 出力 wav のパス。
        wav: 波形配列（任意 dtype）。
        sr: サンプルレート。
    """
    import soundfile as sf  # 関数内 import（重い依存）

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    sf.write(path, _to_float32_clipped(wav), int(sr))


def export_reference(
    wav: np.ndarray,
    sr: int,
    out_dir: str = config.PATHS.output_dir,
    name: str = config.PATHS.reference_name,
) -> str:
    """確定した声を reference.wav として書き出し、そのパスを返す。

    GPT-SoVITS / RVC の参照音声として読み込める wav を出力する。
    `out_dir` は os.makedirs(exist_ok=True) で作成する。

    Args:
        wav: 書き出す波形（任意 dtype。内部で float32 [-1,1] にクリップ）。
        sr: サンプルレート。
        out_dir: 出力先ディレクトリ（既定 config.PATHS.output_dir）。
        name: 出力ファイル名（既定 config.PATHS.reference_name）。

    Returns:
        書き出した wav の絶対パス。
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    save_wav(path, wav, sr)
    return os.path.abspath(path)
