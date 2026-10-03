"""声のCanva (Voice Designer) — Step 2: 軸設計と軸→WORLDパラメータのマッピング。

memo §2.1〜2.3 の設計思想を実装する中核モジュール。

- §2.1: 生 WORLD パラメータ（F0/SP/AP）を独立に動かさず、:data:`config.AXES` の
  ``linked_params`` と :data:`config.GAINS` に従って相関連動させる。
- §2.2: UI に見せる 6 軸は人手設計の「解釈優先」軸。PCA は出さず、相関構造の確認は
  :func:`correlation_matrix` に限定する（内部用途）。
- §2.3: スライダー可動域は実測分布の ±``config.SIGMA_CLIP`` σ に物理的に制限する。
  これを :func:`compute_ranges` で算出し、:func:`apply_axes` の変換量をクリップする。

実装手段（INTERFACES.md のコントラクト）:
- F0: 半音スケーリング（体格/性別で連動。年齢は f0_std 由来の不安定性を、緊張は
  jitter を有声 F0 への微小ゆらぎとして反映）。0（無声）は保持。
- フォルマント: SP の周波数軸ワーピング（線形補間リサンプル）で formant_shift を実現。
- 明るさ: SP のスペクトル傾斜（dB/oct）を周波数依存ゲインで変更。
- 気息: AP のスケーリング（[0,1] にクリップ）。memo §5 に従い保守的に。

依存は numpy のみ（軽量）。SpeakerFeatures は型注釈のみで参照し、解析モジュールの
重い依存を本モジュール import 時に巻き込まない（TYPE_CHECKING 経由）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from voice_canva import config

if TYPE_CHECKING:  # 実行時には import しない（重い依存の巻き込み回避）
    from voice_canva.analysis import SpeakerFeatures


__all__ = [
    "AxisRanges",
    "FEATURE_NAMES",
    "compute_ranges",
    "default_axis_values",
    "apply_axes",
    "correlation_matrix",
]


# ---------------------------------------------------------------------------
# 内部定数
# ---------------------------------------------------------------------------
# 相関分析・可動域算出に用いるスカラ特徴量の並び（Single Source は config の軸定義だが、
# 特徴ベクトルの順序は本モジュールが規定する）。
FEATURE_NAMES: tuple[str, ...] = (
    "f0_mean", "f0_std", "F1", "F2", "F3", "F4",
    "jitter", "shimmer", "hnr", "spectral_tilt",
)

# 話者数が不足（< 2）で σ を実測できない場合のフォールバック相対標準偏差（memo §5/§109）。
# 平均値の絶対値に対する割合として σ を仮置きする。狭め＝保守的に倒す。
_FALLBACK_REL_STD: float = 0.15
# 値の絶対値が小さい特徴は相対% だと σ 域が締まりすぎて軸が効かなくなるため、
# 絶対値でフォールバック σ を与える（例: スペクトル傾斜は -数 dB/oct で rel だと ±2 程度に潰れる）。
_FALLBACK_ABS_STD: dict[str, float] = {
    "spectral_tilt": 3.0,   # dB/oct
}
# σ の下限（数値的退化の回避）。
_STD_EPS: float = 1e-9

# スペクトル傾斜変更（明るさ／緊張軸）の周波数アンカー [Hz]。この周波数のゲインは不変。
_BRIGHTNESS_PIVOT_HZ: float = 1000.0
# 傾斜適用の低域アンカー [Hz]。これ未満は一定利得（log2(f/pivot) の発散＝DC 過剰増幅を防ぐ）。
_TILT_FREQ_FLOOR_HZ: float = 100.0
# 傾斜 per-bin 利得の上限 [dB]（単一ビンが支配して音が割れるのを防ぐ）。
_MAX_TILT_GAIN_DB: float = 12.0
# 気息ハスキー側の高域ノイズ床を与える下限周波数 [Hz]。
_BREATH_HF_HZ: float = 2000.0
# AP ガンマ指数の安全範囲（正値・破綻回避）。
_AP_EXP_MIN: float = 0.15
_AP_EXP_MAX: float = 3.0

# F0 微小ゆらぎ（jitter）/ 振幅ゆらぎ（shimmer）の安全上限（無次元・相対）。
# memo §5 の「やりすぎると別人化／機械臭」を踏まえ破綻しない範囲に制限する。
_MAX_JITTER_REL: float = 0.04
_MAX_SHIMMER_REL: float = 0.15
# 摂動の決定論シード（スライダー操作のたびに音が変わらないよう固定）。
_PERTURB_SEED: int = 20240628

# SP の下限（正値保証）。
_SP_FLOOR: float = 1e-12


# ---------------------------------------------------------------------------
# 可動域（±σ）
# ---------------------------------------------------------------------------
@dataclass
class AxisRanges:
    """各軸の物理可動域（±``config.SIGMA_CLIP`` σ ベース）。

    Attributes:
        per_axis: 軸 key → その軸の代表物理量の (min, max)。正規化外の参考値。
        feature_ranges: スカラ特徴名 → (mean-Nσ, mean+Nσ)。:func:`apply_axes` が
            変換量を物理域へクリップする際に参照する内部レンジ。
        n_speakers: 母集団の話者数（σ 推定の信頼度の目安。< 2 はフォールバック）。
    """

    per_axis: dict[str, tuple[float, float]]
    feature_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    n_speakers: int = 0


def _feature_vector(f: "SpeakerFeatures") -> np.ndarray:
    """1 話者を :data:`FEATURE_NAMES` 順のスカラベクトルへ変換する。"""
    formants = np.asarray(f.formants, dtype=np.float64).reshape(-1)
    # F1..F4 が欠ける場合に備え 4 要素へパディング（NaN）。
    f1234 = np.full(4, np.nan, dtype=np.float64)
    f1234[: min(4, formants.size)] = formants[:4]
    return np.array(
        [
            float(f.f0_mean), float(f.f0_std),
            f1234[0], f1234[1], f1234[2], f1234[3],
            float(f.jitter), float(f.shimmer),
            float(f.hnr), float(f.spectral_tilt),
        ],
        dtype=np.float64,
    )


def _sigma_range(values: np.ndarray, name: str = "") -> tuple[float, float]:
    """値配列から平均 ± ``config.SIGMA_CLIP`` σ のレンジを返す。

    話者数 < 2 もしくは σ ≈ 0 の場合はフォールバック σ を用いる（memo §5: 少話者では
    厳密 σ 推定不能のため代表アンカー＋補間用途と割り切る）。フォールバックは特徴ごとに
    :data:`_FALLBACK_ABS_STD`（絶対値）優先、無ければ :data:`_FALLBACK_REL_STD`（相対）。
    実測 σ が得られる場合（話者 ≥ 2）はフォールバックを適用しない。
    """
    v = np.asarray(values, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return (0.0, 0.0)
    mean = float(np.mean(v))
    if v.size >= 2:
        std = float(np.std(v, ddof=1))
    else:
        std = 0.0
    if std <= _STD_EPS:
        if name in _FALLBACK_ABS_STD:
            std = _FALLBACK_ABS_STD[name] + _STD_EPS
        else:
            std = abs(mean) * _FALLBACK_REL_STD + _STD_EPS
    half = config.SIGMA_CLIP * std
    return (mean - half, mean + half)


def compute_ranges(features: list["SpeakerFeatures"]) -> AxisRanges:
    """実測分布から各軸／各特徴の ±σ 可動域を算出する（memo §2.3, Step 2）。

    Args:
        features: 母集団となる話者特徴のリスト（1 つ以上）。

    Returns:
        :class:`AxisRanges`。``feature_ranges`` は各スカラ特徴の ±σ レンジ、
        ``per_axis`` は各軸の代表物理量の (min, max)。
    """
    if not features:
        raise ValueError("compute_ranges: features が空です（1 話者以上が必要）")

    matrix = np.vstack([_feature_vector(f) for f in features])  # (N, D)

    feature_ranges: dict[str, tuple[float, float]] = {}
    for j, name in enumerate(FEATURE_NAMES):
        feature_ranges[name] = _sigma_range(matrix[:, j], name)

    # フォルマント全体スケール（声道長の代理）の母集団レンジ。
    formant_means = np.nanmean(matrix[:, 2:6], axis=1)  # 各話者の F1..F4 平均
    feature_ranges["formant_mean"] = _sigma_range(formant_means, "formant_mean")

    # 各軸の代表物理量を per_axis に据える（UI/検証用の参考レンジ）。
    per_axis: dict[str, tuple[float, float]] = {
        "build": feature_ranges["formant_mean"],   # 声道長（フォルマント全体）
        "gender": feature_ranges["f0_mean"],        # F0
        "brightness": feature_ranges["spectral_tilt"],
        "tension": feature_ranges["jitter"],
        "breath": feature_ranges["hnr"],
        "age": feature_ranges["shimmer"],
    }

    return AxisRanges(
        per_axis=per_axis,
        feature_ranges=feature_ranges,
        n_speakers=len(features),
    )


def default_axis_values() -> dict[str, float]:
    """全軸 0.0（= ベース話者そのまま）の軸値を返す。"""
    return {key: 0.0 for key in config.AXIS_KEYS}


# ---------------------------------------------------------------------------
# 相関行列（内部用・memo §2.2 / Step 2）
# ---------------------------------------------------------------------------
def correlation_matrix(features: list["SpeakerFeatures"]) -> np.ndarray:
    """スカラ特徴間の Pearson 相関行列 (D, D) を返す（:data:`FEATURE_NAMES` 順）。

    軸→パラメータ変換の相関構造を内部確認するための補助関数。UI には出さない（§2.2）。
    話者数 < 2 では相関を定義できないため、対角 1・非対角 NaN の行列を返す。
    """
    if not features:
        raise ValueError("correlation_matrix: features が空です")

    matrix = np.vstack([_feature_vector(f) for f in features])  # (N, D)
    d = matrix.shape[1]

    if matrix.shape[0] < 2:
        out = np.full((d, d), np.nan, dtype=np.float64)
        np.fill_diagonal(out, 1.0)
        return out

    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(matrix, rowvar=False)
    return np.asarray(corr, dtype=np.float64)


# ---------------------------------------------------------------------------
# 軸 → WORLD パラメータ変換
# ---------------------------------------------------------------------------
def _resolve_axes(axis_values: dict[str, float]) -> dict[str, float]:
    """部分指定の軸値を全軸ぶんに補完し、[AXIS_MIN, AXIS_MAX] にクリップする。"""
    resolved = default_axis_values()
    for key, val in axis_values.items():
        if key not in resolved:
            raise KeyError(f"apply_axes: 未知の軸 key: {key!r}")
        resolved[key] = float(np.clip(val, config.AXIS_MIN, config.AXIS_MAX))
    return resolved


def _warp_spectrum(sp: np.ndarray, freqs: np.ndarray, scale: float) -> np.ndarray:
    """SP を周波数軸方向に ``scale`` 倍ワーピングする（フォルマントシフト）。

    ``scale`` > 1 でフォルマントは高域へ移動（声道短縮＝細い/女性的）。
    新スペクトル new[f] は旧スペクトルの freq ``f/scale`` の値（線形補間）。
    全フレーム共通の補間係数を 1 度だけ求めてベクトル化する。
    """
    if abs(scale - 1.0) < 1e-6:
        return sp
    fmax = float(freqs[-1])
    query = np.clip(freqs / scale, 0.0, fmax)             # (F,)
    idx = np.clip(np.searchsorted(freqs, query, side="right") - 1, 0, freqs.size - 2)
    f0v = freqs[idx]
    f1v = freqs[idx + 1]
    denom = np.where((f1v - f0v) > 0, (f1v - f0v), 1.0)
    w = (query - f0v) / denom                              # (F,)
    left = sp[:, idx]                                      # (T, F)
    right = sp[:, idx + 1]
    return left * (1.0 - w) + right * w


def apply_axes(
    axis_values: dict[str, float],
    base: "SpeakerFeatures",
    ranges: "AxisRanges | None" = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """軸値（正規化 -1..+1）とベース話者特徴から、変更後の WORLD パラメータを返す。

    生パラメータを独立に動かさず、:data:`config.GAINS` と :class:`AxisRanges`（±σ）に
    従って相関連動させる（memo §2.1/§2.3）。

    Args:
        axis_values: 軸 key → 値（部分指定可。未指定軸は 0.0）。
        base: ベース話者の特徴（f0/sp/ap と各スカラ統計）。
        ranges: 可動域。None の場合は ``compute_ranges([base])`` でフォールバック。

    Returns:
        ``(f0_mod, sp_mod, ap_mod)``。いずれも float64・C 連続で
        ``pyworld.synthesize`` にそのまま渡せる。
    """
    if ranges is None:
        ranges = compute_ranges([base])

    ax = _resolve_axes(axis_values)
    g = config.GAINS
    fr = ranges.feature_ranges

    sr = int(base.sr)
    f0 = np.array(base.f0, dtype=np.float64, copy=True)            # (T,)
    sp = np.array(base.sp, dtype=np.float64, copy=True)            # (T, F)
    ap = np.array(base.ap, dtype=np.float64, copy=True)            # (T, F)

    n_frames, n_bins = sp.shape
    freqs = np.linspace(0.0, sr / 2.0, n_bins)                    # (F,)
    voiced = f0 > 0.0
    rng = np.random.default_rng(_PERTURB_SEED)

    # -- (1) F0: 半音スケーリング（体格 + 性別 + 緊張 + 年齢の複合）----------
    # build +1(細い)→微増, gender +1(女性的)→上昇, tension -1(張った)→上昇,
    # age +1(年配)→低下。すべて相関連動として 1 本の半音シフトに合算する（§2.1）。
    semitones = (
        ax["build"] * g.build_f0_semitones
        + ax["gender"] * g.gender_f0_semitones
        - ax["tension"] * g.tension_f0_semitones   # 張った(-1)で +
        - ax["age"] * g.age_f0_semitones           # 年配(+1)で -
    )

    if np.any(voiced):
        vmean = float(np.mean(f0[voiced]))
        # ±σ 物理域（f0_mean）に収まるよう半音シフト量をクリップ（§2.3）。
        lo, hi = fr.get("f0_mean", (vmean, vmean))
        if vmean > 0:
            up_lim = 12.0 * np.log2(hi / vmean) if hi > 0 else 0.0
            dn_lim = 12.0 * np.log2(lo / vmean) if lo > 0 else 0.0
            lo_s, hi_s = sorted((dn_lim, up_lim))
            semitones = float(np.clip(semitones, lo_s, hi_s))
        f0[voiced] *= 2.0 ** (semitones / 12.0)

        # -- (2) F0 ゆらぎ: jitter（年齢の粗さ）------------------------------
        # age +1(年配)→ F0 安定性低下＝粗さ。base.jitter に依存させず軸から直接
        # 目標 jitter を与える（ベースの jitter が小さいと不可聴になる問題を回避）。
        # 中立 0 では 0 ＝恒等。
        jit_rel = float(np.clip(max(0.0, ax["age"]) * g.age_jitter, 0.0, _MAX_JITTER_REL))
        if jit_rel > 0.0:
            pert = rng.standard_normal(int(np.count_nonzero(voiced)))
            f0[voiced] *= np.clip(1.0 + jit_rel * pert, 1e-3, None)

    # -- (3) フォルマント: SP 周波数軸ワーピング（体格 + 性別 + 年齢）--------
    # age +1(年配)→ フォルマント低下（声道変化の代理）で「重さ／老け」を補強。
    fscale = (
        (1.0 + ax["build"] * g.build_formant_shift)
        * (1.0 + ax["gender"] * g.gender_formant_shift)
        * (1.0 - ax["age"] * g.age_formant_shift)
    )
    base_fmean = float(np.nanmean(np.asarray(base.formants, dtype=np.float64)))
    flo, fhi = fr.get("formant_mean", (base_fmean, base_fmean))
    if base_fmean > 0 and np.isfinite(base_fmean):
        target = float(np.clip(base_fmean * fscale, flo, fhi))
        fscale = target / base_fmean
    sp = _warp_spectrum(sp, freqs, fscale)

    # -- (4) スペクトル傾斜: 明るさ + 緊張 ----------------------------------
    # brightness +1(こもった)→ 傾斜を急に（高域減衰）。
    # tension -1(張った)→ 高域増（明るく張る）/ +1(リラックス)→ 高域減（柔らかい）。
    delta_tilt = -ax["brightness"] * g.brightness_tilt_db \
        - ax["tension"] * g.tension_tilt_db
    base_tilt = float(base.spectral_tilt)
    tlo, thi = fr.get("spectral_tilt", (base_tilt, base_tilt))
    new_tilt = float(np.clip(base_tilt + delta_tilt, tlo, thi))
    delta_tilt = new_tilt - base_tilt
    if abs(delta_tilt) > 1e-9:
        # 低域はアンカー（_TILT_FREQ_FLOOR_HZ 未満は一定）で log2 の発散を断ち、
        # per-bin 利得を ±_MAX_TILT_GAIN_DB に制限して単一ビンの暴走を防ぐ。
        fmax = float(freqs[-1]) if freqs[-1] > 0 else _TILT_FREQ_FLOOR_HZ
        f_anchored = np.clip(freqs, _TILT_FREQ_FLOOR_HZ, fmax)
        gain_db = delta_tilt * np.log2(f_anchored / _BRIGHTNESS_PIVOT_HZ)   # (F,)
        gain_db = np.clip(gain_db, -_MAX_TILT_GAIN_DB, _MAX_TILT_GAIN_DB)
        gain = 10.0 ** (gain_db / 10.0)
        # エネルギ保存: 傾斜は音色変化でありラウドネスは変えない。各フレームの総パワーを
        # 維持して、低域過剰増幅→ピーク正規化での潰れ（割れ）を根本的に防ぐ。
        e_before = sp.sum(axis=1, keepdims=True)
        sp = sp * gain[None, :]
        e_after = sp.sum(axis=1, keepdims=True)
        scale = np.divide(e_before, e_after, out=np.ones_like(e_before), where=e_after > 0.0)
        sp = sp * scale

    # -- (5) 振幅ゆらぎ: shimmer（年齢の粗さ）------------------------------
    # age +1(年配)→ shimmer 増。軸から直接目標 shimmer を与える（中立 0 で恒等）。
    shim_rel = float(np.clip(max(0.0, ax["age"]) * g.age_shimmer, 0.0, _MAX_SHIMMER_REL))
    if shim_rel > 0.0 and np.any(voiced):
        amp = np.clip(1.0 + shim_rel * rng.standard_normal(n_frames), 1e-3, None)
        amp = np.where(voiced, amp, 1.0)
        sp *= (amp ** 2)[:, None]      # SP は power 包絡なので振幅倍率は二乗で効かせる

    # -- (6) 気息: AP のガンマ指数写像（気息 + 緊張 + 年齢）----------------
    # clarity > 0 ほどクリア（AP↓）, < 0 ほどハスキー（AP↑）。
    #   breath +1(クリア)→ +, tension -1(張った)→ +（締まった声）,
    #   age +1(年配)→ -（気息増）。
    # AP^exp（exp>1 で AP 低下＝クリア, exp<1 で AP 上昇＝ハスキー）。線形スケールより
    # [0,1] 全域で可聴な変化が出る。中立 0 では exp=1 ＝恒等。
    clarity = (
        ax["breath"] * g.breath_gamma
        - ax["tension"] * g.tension_breath
        - max(0.0, ax["age"]) * g.age_breath
    )
    exp = float(np.clip(1.0 + clarity, _AP_EXP_MIN, _AP_EXP_MAX))
    if abs(exp - 1.0) > 1e-9:
        ap = np.power(np.clip(ap, 0.0, 1.0), exp)
    # ハスキー側（clarity < 0）は高域に非周期ノイズ床を足して気息感を補強する。
    if clarity < 0.0 and np.any(voiced):
        husky = min(-clarity, 1.0)
        floor = g.breath_hf_floor * husky
        hf = freqs >= _BREATH_HF_HZ
        if np.any(hf):
            block = ap[np.ix_(voiced, hf)]
            ap[np.ix_(voiced, hf)] = np.maximum(block, floor)
    ap = np.clip(ap, 0.0, 1.0)

    # -- 仕上げ: 正値保証 & pyworld 互換の連続 float64 -----------------------
    sp = np.maximum(sp, _SP_FLOOR)
    f0_mod = np.ascontiguousarray(f0, dtype=np.float64)
    sp_mod = np.ascontiguousarray(sp, dtype=np.float64)
    ap_mod = np.ascontiguousarray(ap, dtype=np.float64)
    return f0_mod, sp_mod, ap_mod
