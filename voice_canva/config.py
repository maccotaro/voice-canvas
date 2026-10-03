"""声のCanva (Voice Designer) — 全モジュール共有の定数・軸定義（Single Source of Truth）。

このファイルは各実装モジュール（analysis / axes / synthesis / app）が参照する
唯一の設定源である。軸の定義・連動パラメータ・既定値はすべてここに集約する。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 信号処理の基本設定
# ---------------------------------------------------------------------------
# pyworld は音声のネイティブサンプルレートで動作する。読み込み時にこのレートへ
# リサンプルしてからパイプライン全体を統一する。
DEFAULT_SR: int = 24000

# WORLD のフレーム周期 [ms]。pyworld の既定 5.0ms を採用。
FRAME_PERIOD: float = 5.0

# F0 探索範囲 [Hz]（harvest/dio 用）。
F0_FLOOR: float = 71.0
F0_CEIL: float = 800.0

# F0 シフトの破綻ガードレール [半音]（memo §2.3）。WORLD は大きな上方ピッチ移動で
# 急速に劣化する（実測: +7 半音あたりから聞き苦しくなる）。話者間モーフ等で F0 を
# 動かす量をこの範囲に物理制限し、ユーザーが破綻領域へ到達できないようにする。
# 下方シフトは比較的頑健なため上方より緩く許す。
MAX_PITCH_UP_SEMITONES: float = 6.0
MAX_PITCH_DOWN_SEMITONES: float = 9.0

# 可動域は実測分布の ±N σ に物理的に制限する（memo §2.3）。
SIGMA_CLIP: float = 2.0

# 各軸スライダーの連続値レンジ（UI 上の正規化値）。
AXIS_MIN: float = -1.0
AXIS_MAX: float = 1.0


# ---------------------------------------------------------------------------
# 6 軸定義（memo §2.2）。UI には「解釈優先」の意味づけ軸のみを見せる。
# linked_params は axes.py が軸値 → WORLD パラメータ変換で連動させる物理量の識別子。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Axis:
    key: str                 # 内部識別子
    label: str               # 軸名（日本語）
    low: str                 # スライダー左端（AXIS_MIN 側）のラベル
    high: str                # スライダー右端（AXIS_MAX 側）のラベル
    linked_params: tuple[str, ...]  # 連動する物理パラメータ識別子
    description: str = ""


AXES: tuple[Axis, ...] = (
    Axis("build", "体格", "太い", "細い",
         ("vocal_tract_length", "f0"),
         "声道長（フォルマント全体スケール）と F0 を相関連動"),
    Axis("gender", "性別印象", "男性的", "女性的",
         ("f0", "formant_shift"),
         "F0 とフォルマントを相関連動"),
    Axis("brightness", "明るさ", "明るい", "こもった",
         ("spectral_tilt", "high_formant_gain"),
         "高域フォルマント／スペクトル傾斜"),
    Axis("tension", "緊張", "張った", "リラックス",
         ("tension", "jitter"),
         "tension と jitter を相関連動"),
    Axis("breath", "気息", "ハスキー", "クリア",
         ("aperiodicity", "hnr"),
         "非周期成分（気息）と HNR。AP 操作は荒いので可動域は保守的に"),
    Axis("age", "年齢印象", "若い", "年配",
         ("shimmer", "f0_stability"),
         "shimmer と F0 安定性"),
)

AXIS_KEYS: tuple[str, ...] = tuple(a.key for a in AXES)


def axis_by_key(key: str) -> Axis:
    for a in AXES:
        if a.key == key:
            return a
    raise KeyError(f"unknown axis key: {key!r}")


# ---------------------------------------------------------------------------
# 軸 → 物理パラメータ変換のゲイン（保守的初期値）。
# axes.py がこのゲインと ±2σ 可動域を掛け合わせて連動量を決める。
# 値はすべて「軸値 +1.0 のときに適用する相対変化の最大量」を表す。
# 気息（breath）は memo §5 の警告に従い保守的に小さく設定。
# ---------------------------------------------------------------------------
@dataclass
class AxisGains:
    # 体格: +1(細い)で声道短縮→フォルマント上方シフト、F0 微増
    build_formant_shift: float = 0.12   # フォルマント周波数の相対スケール幅
    build_f0_semitones: float = 1.5     # F0 の半音変化幅
    # 性別: +1(女性的)で F0 上昇・フォルマント上方シフト
    gender_f0_semitones: float = 3.0
    gender_formant_shift: float = 0.10
    # 明るさ: +1(こもった)でスペクトル傾斜を急に（高域減衰）
    brightness_tilt_db: float = 6.0     # スペクトル傾斜の dB/oct 変化幅
    # 緊張: 張った(-1)⇄リラックス(+1)。jitter 単独では不可聴のため、知覚的に強い
    #   スペクトル傾斜・F0・わずかな気息の複合レバーで実現する。
    tension_tilt_db: float = 5.0        # 張った(-1)→高域増(明るい)/リラックス(+1)→高域減
    tension_f0_semitones: float = 1.5   # 張った(-1)→F0 上昇
    tension_breath: float = 0.10        # リラックス(+1)→わずかに気息増
    # 気息: ハスキー(-1)⇄クリア(+1)。AP を線形ではなくガンマ指数で写像し、[0,1] 全域で
    #   可聴な変化を出す。ハスキー側は高域ノイズ床を足す。memo §5 に従い上限を設ける。
    breath_gamma: float = 0.8          # |breath|=1 で AP の指数を 1±0.8 に
    breath_hf_floor: float = 0.30      # ハスキー側で高域 AP に与える床
    # 年齢: 若い(-1)⇄年配(+1)。shimmer 微小ゆらぎ単独では不可聴のため、F0 低下・
    #   フォルマント低下・jitter/shimmer(粗さ)・気息増の複合で「老け／若さ」を作る。
    age_f0_semitones: float = 2.0      # 年配(+1)→F0 を 2 半音下げる
    age_formant_shift: float = 0.05    # 年配(+1)→フォルマント×(1-0.05)
    age_jitter: float = 0.025          # 年配(+1)時の目標 jitter（直接指定）
    age_shimmer: float = 0.06          # 年配(+1)時の目標 shimmer 振幅ゆらぎ
    age_breath: float = 0.12           # 年配(+1)→気息増


GAINS = AxisGains()


# ---------------------------------------------------------------------------
# 既定の入出力パス
# ---------------------------------------------------------------------------
@dataclass
class Paths:
    data_dir: str = "data"            # 入力 wav 置き場
    features_dir: str = "features"    # 抽出特徴量（npz/json）置き場
    output_dir: str = "output"        # reference.wav 書き出し先
    reference_name: str = "reference.wav"


PATHS = Paths()
