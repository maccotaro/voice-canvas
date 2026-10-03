"""声のCanva (Voice Designer) — Step 3: 再合成エンジン。

6 軸の値とベース話者の WORLD 構造（F0/SP/AP）から、軸 → パラメータ変換を経て
`pyworld.synthesize` で波形を生成する。スライダー操作 → 即試聴ループのため、
1 文あたり数百 ms〜秒で返る軽量実装とする（memo §4 Step 3）。

設計方針:
- 軸 → WORLD パラメータの相関連動は `axes.apply_axes` に一元化する（memo §2.1）。
  本モジュールは「合成」のみを担い、変換則は持たない（重複定義禁止）。
- 出力は float32 mono (T,)。NaN/Inf をガードし [-1, 1] にクリップして返す。
- 重い依存（pyworld, axes 配下の librosa 等）は import 時クラッシュを避けるため
  関数内 import を用いる。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from . import config

if TYPE_CHECKING:  # 型チェック時のみ。実行時の循環/重依存 import を避ける。
    from .analysis import SpeakerFeatures
    from .axes import AxisRanges


# 再生時のフルスケール余裕（ピーク超過時はこの値へ縮小正規化する）。
_PEAK_CEIL: float = 0.97


def _sanitize(wav: np.ndarray) -> np.ndarray:
    """合成波形を安全な再生用信号へ整える。

    NaN/Inf を 0 に置換し、float32 mono (T,) として無害化する。
    WORLD 合成では稀に数値破綻（高 F0・気息操作）で非有限値が混じるため、
    例外で握りつぶさず値レベルで根本的に無害化する（memo §5）。

    振幅が ``_PEAK_CEIL`` を超える場合はハードクリップせず**ピーク縮小正規化**する。
    WORLD 合成出力は素の状態でしばしば 1.0 を超え（実測 peak≈1.2）、ハードクリップ
    すると数値破綻ではない正規の波形に歪みが乗る。波形形状を保つ縮小で根本回避する。
    小音量側は増幅しない（編集 A/B 時の相対ラウドネス知覚を保つため）。
    """
    arr = np.asarray(wav, dtype=np.float32).reshape(-1)
    # まず非有限値だけ有限化（NaN→0, ±Inf→±1）。
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak > _PEAK_CEIL:
        arr = arr * (_PEAK_CEIL / peak)
    return arr


def synthesize(
    axis_values: dict[str, float],
    base: "SpeakerFeatures",
    ranges: "AxisRanges | None" = None,
) -> np.ndarray:
    """6 軸の値とベース話者特徴から編集後の波形を再合成する。

    Parameters
    ----------
    axis_values:
        軸キー（``config.AXIS_KEYS``）→ 正規化値（``config.AXIS_MIN``..``AXIS_MAX``）。
        欠けた軸は ``axes.apply_axes`` 側で 0.0（=ベースのまま）として扱われる。
    base:
        ベース話者の WORLD 構造とスカラ統計を保持する ``SpeakerFeatures``。
    ranges:
        各軸の物理可動域（±2σ ベース）。``None`` のとき ``apply_axes`` が既定で補う。

    Returns
    -------
    np.ndarray
        float32 mono 波形 (T,)。NaN/Inf ガード済み・[-1, 1] クリップ済み。

    Notes
    -----
    軸 → WORLD パラメータの相関連動は ``axes.apply_axes`` に委譲する（memo §2.1）。
    本関数は変換結果を ``pyworld.synthesize`` に渡して波形化するだけに徹する。
    """
    # 関数内 import: 重い依存（pyworld）と自モジュール（axes）の import 時クラッシュ回避。
    import pyworld as pw

    from .axes import apply_axes

    f0_mod, sp_mod, ap_mod = apply_axes(axis_values, base, ranges)

    # pyworld.synthesize は C-contiguous な float64 を要求する。
    f0_c = np.ascontiguousarray(f0_mod, dtype=np.float64)
    sp_c = np.ascontiguousarray(sp_mod, dtype=np.float64)
    ap_c = np.ascontiguousarray(ap_mod, dtype=np.float64)

    wav = pw.synthesize(
        f0_c,
        sp_c,
        ap_c,
        int(base.sr),
        float(base.frame_period),
    )
    return _sanitize(wav)


def resynthesize(base: "SpeakerFeatures") -> np.ndarray:
    """編集を加えない素の再合成（Step 0 の地盤確認用）。

    全軸 0.0（ベース話者そのまま）で ``synthesize`` を呼び、原音相当に戻るかの
    確認に用いる。軸変換を経るため ``apply_axes`` が恒等変換である前提を満たすかの
    検証も兼ねる（memo §4 Step 0）。

    Parameters
    ----------
    base:
        ベース話者の ``SpeakerFeatures``。

    Returns
    -------
    np.ndarray
        float32 mono 波形 (T,)。
    """
    from .axes import default_axis_values

    return synthesize(default_axis_values(), base, None)
