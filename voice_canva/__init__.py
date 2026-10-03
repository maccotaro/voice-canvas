"""声のCanva (Voice Designer) パッケージ。

実在話者から抽出した音声パラメータをもとに、人手設計の 6 軸スライダーで声質を
デザインし reference.wav として書き出すためのツール群。

このモジュールは各サブモジュールの主要シンボルを re-export して公開 API を提供する。
重い依存（pyworld / parselmouth / librosa 等）はサブモジュール側で関数内 import
しているため、本パッケージの import 自体は軽量で副作用を持たない。
"""
from __future__ import annotations

__version__ = "0.1.0"

# 設定（Single Source of Truth）。
from . import config as config
from .config import (
    AXES,
    AXIS_KEYS,
    AXIS_MAX,
    AXIS_MIN,
    DEFAULT_SR,
    FRAME_PERIOD,
    GAINS,
    PATHS,
    SIGMA_CLIP,
    Axis,
    axis_by_key,
)

# 分析（特徴抽出）。
from .analysis import (
    SpeakerFeatures,
    analyze_dir,
    analyze_wav,
)

# 軸マッピング。
from .axes import (
    AxisRanges,
    apply_axes,
    compute_ranges,
    default_axis_values,
)

# 再合成。
from .synthesis import synthesize

# 音声 I/O。
from .io_utils import (
    export_reference,
    load_wav,
    save_wav,
)

__all__ = [
    "__version__",
    # config
    "config",
    "AXES",
    "AXIS_KEYS",
    "AXIS_MIN",
    "AXIS_MAX",
    "DEFAULT_SR",
    "FRAME_PERIOD",
    "GAINS",
    "PATHS",
    "SIGMA_CLIP",
    "Axis",
    "axis_by_key",
    # analysis
    "SpeakerFeatures",
    "analyze_wav",
    "analyze_dir",
    # axes
    "AxisRanges",
    "compute_ranges",
    "default_axis_values",
    "apply_axes",
    # synthesis
    "synthesize",
    # io_utils
    "load_wav",
    "save_wav",
    "export_reference",
]
