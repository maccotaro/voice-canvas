"""axes（軸 → WORLD パラメータ変換）の単体検証。

合成（ダミー）の :class:`SpeakerFeatures` を numpy だけで組み立て、pyworld /
parselmouth / librosa に一切依存せずに axes.py の契約を検証する（INTERFACES.md）。

検証内容:
- ``default_axis_values`` が全軸 0.0（= ベース話者そのまま; memo §2.2）。
- ``apply_axes`` が F0/SP/AP の形状を保つ。
- 軸を +1 にすると F0 平均が期待方向へ動く（性別 +1=女性的→上、体格 +1=細い→微増）。
- 可動域（±σ）クリップが効き、軸値そのものも [AXIS_MIN, AXIS_MAX] にクリップされる
  （memo §2.3：破綻領域へ到達できない）。
"""
from __future__ import annotations

import numpy as np
import pytest

from voice_canva import config
from voice_canva.analysis import SpeakerFeatures
from voice_canva.axes import apply_axes, compute_ranges, default_axis_values


# ---------------------------------------------------------------------------
# ダミー話者特徴（pyworld 不要）
# ---------------------------------------------------------------------------
def _make_dummy(
    n_frames: int = 60,
    n_bins: int = 64,
    f0_value: float = 120.0,
    jitter: float = 0.0,
    shimmer: float = 0.0,
) -> SpeakerFeatures:
    """合成の SpeakerFeatures を生成する。

    有声フレームの F0 は定数 ``f0_value``、末尾数フレームを無声(0)にして無声保持を
    検証可能にする。jitter/shimmer は既定 0.0 で、方向・クリップ検証時に摂動が
    入らないよう決定論的にしておく。
    """
    f0 = np.full(n_frames, f0_value, dtype=np.float64)
    f0[-5:] = 0.0  # 末尾を無声に
    # SP は power 包絡を模した正の滑らかな配列、AP は [0,1] の中間値。
    sp = np.linspace(1.0, 0.1, n_bins, dtype=np.float64)[None, :] * np.ones((n_frames, 1))
    ap = np.full((n_frames, n_bins), 0.5, dtype=np.float64)
    return SpeakerFeatures(
        name="dummy",
        sr=config.DEFAULT_SR,
        frame_period=config.FRAME_PERIOD,
        f0=f0,
        sp=sp,
        ap=ap,
        f0_mean=f0_value,
        f0_std=5.0,
        formants=np.array([500.0, 1500.0, 2500.0, 3500.0], dtype=np.float64),
        jitter=jitter,
        shimmer=shimmer,
        hnr=15.0,
        spectral_tilt=-6.0,
    )


def _voiced_mean(f0: np.ndarray) -> float:
    """有声フレーム（F0>0）の平均 F0 を返す。"""
    voiced = f0 > 0.0
    return float(np.mean(f0[voiced]))


# ---------------------------------------------------------------------------
# default_axis_values
# ---------------------------------------------------------------------------
def test_default_axis_values_all_zero() -> None:
    """全軸 0.0 かつ key は config.AXIS_KEYS と一致。"""
    dv = default_axis_values()
    assert set(dv.keys()) == set(config.AXIS_KEYS)
    assert all(v == 0.0 for v in dv.values())


def test_zero_axes_is_near_identity() -> None:
    """全軸 0.0（jitter/shimmer=0）の変換はベース構造をほぼ保つ。"""
    base = _make_dummy()
    f0_mod, sp_mod, ap_mod = apply_axes(default_axis_values(), base)
    assert np.allclose(f0_mod, base.f0)
    assert np.allclose(sp_mod, base.sp)
    assert np.allclose(ap_mod, base.ap)


# ---------------------------------------------------------------------------
# 形状保存
# ---------------------------------------------------------------------------
def test_apply_axes_preserves_shapes() -> None:
    """apply_axes は F0(T,)・SP(T,F)・AP(T,F) の形状を保つ。"""
    base = _make_dummy(n_frames=48, n_bins=80)
    values = {key: 0.5 for key in config.AXIS_KEYS}
    f0_mod, sp_mod, ap_mod = apply_axes(values, base)
    assert f0_mod.shape == base.f0.shape
    assert sp_mod.shape == base.sp.shape
    assert ap_mod.shape == base.ap.shape
    # 数値破綻していない。
    assert np.all(np.isfinite(f0_mod))
    assert np.all(np.isfinite(sp_mod))
    assert np.all(np.isfinite(ap_mod))


def test_unvoiced_frames_stay_zero() -> None:
    """無声フレーム（F0=0）は F0 操作後も 0 のまま。"""
    base = _make_dummy()
    f0_mod, _, _ = apply_axes({"gender": 1.0, "build": 1.0}, base)
    unvoiced = base.f0 == 0.0
    assert np.all(f0_mod[unvoiced] == 0.0)


# ---------------------------------------------------------------------------
# 方向性（軸 +1 で F0 平均が期待方向へ）
# ---------------------------------------------------------------------------
def test_gender_axis_raises_f0() -> None:
    """性別 +1（女性的）で有声 F0 平均が上昇、-1 で下降する。"""
    base = _make_dummy()
    base_mean = _voiced_mean(base.f0)

    up, _, _ = apply_axes({"gender": 1.0}, base)
    down, _, _ = apply_axes({"gender": -1.0}, base)

    assert _voiced_mean(up) > base_mean
    assert _voiced_mean(down) < base_mean


def test_build_axis_raises_f0() -> None:
    """体格 +1（細い）で有声 F0 平均が微増する。"""
    base = _make_dummy()
    base_mean = _voiced_mean(base.f0)
    up, _, _ = apply_axes({"build": 1.0}, base)
    assert _voiced_mean(up) > base_mean


def test_breath_axis_scales_aperiodicity() -> None:
    """気息 +1（クリア）で AP 低下、-1（ハスキー）で AP 上昇（[0,1] 内）。"""
    base = _make_dummy()
    _, _, ap_clear = apply_axes({"breath": 1.0}, base)
    _, _, ap_husky = apply_axes({"breath": -1.0}, base)
    assert np.mean(ap_clear) < np.mean(base.ap)
    assert np.mean(ap_husky) > np.mean(base.ap)
    assert np.all(ap_clear >= 0.0) and np.all(ap_clear <= 1.0)
    assert np.all(ap_husky >= 0.0) and np.all(ap_husky <= 1.0)


# ---------------------------------------------------------------------------
# 可動域クリップ（memo §2.3）
# ---------------------------------------------------------------------------
def test_axis_value_is_clipped_to_unit_range() -> None:
    """レンジ外の軸値（例 +5.0）は AXIS_MAX 相当へクリップされる。"""
    base = _make_dummy()
    ranges = compute_ranges([base])
    over, _, _ = apply_axes({"gender": 5.0}, base, ranges)
    edge, _, _ = apply_axes({"gender": config.AXIS_MAX}, base, ranges)
    assert np.allclose(over, edge)


def test_f0_clipped_to_sigma_range() -> None:
    """F0 は ±σ 物理域（feature_ranges["f0_mean"]）の上限を超えない。

    実測分布が狭い（話者の F0 がほぼ揃う）母集団では ±σ 域も狭くなり、軸を
    強く振っても破綻領域へ到達できない（memo §2.3）。クリップが実際に効く状況を
    作るため、F0 が近接した複数話者から ranges を算出する。
    """
    # F0_mean が 118/122 の 2 話者 → ±σ 域は ~±5.7Hz と狭い。
    population = [_make_dummy(f0_value=118.0), _make_dummy(f0_value=122.0)]
    base = _make_dummy(f0_value=120.0)
    ranges = compute_ranges(population)
    lo, hi = ranges.feature_ranges["f0_mean"]

    # 体格 +1・性別 +1（要求 4.5 半音 ≈ +30%）は狭い ±σ 域を超える → 上限へクリップ。
    f0_mod, _, _ = apply_axes({"gender": 1.0, "build": 1.0}, base, ranges)
    voiced = f0_mod > 0.0
    assert np.max(f0_mod[voiced]) <= hi + 1e-6
    # クリップが実際に効き、上限に張り付く（無制限なら ~156Hで hi を大きく超過する）。
    assert np.max(f0_mod[voiced]) == pytest.approx(hi, rel=1e-6)

    # 下方向（-1）も同様に下限でクリップされる。
    f0_dn, _, _ = apply_axes({"gender": -1.0, "build": -1.0}, base, ranges)
    voiced_dn = f0_dn > 0.0
    assert np.min(f0_dn[voiced_dn]) >= lo - 1e-6
    assert np.min(f0_dn[voiced_dn]) == pytest.approx(lo, rel=1e-6)


def test_unknown_axis_key_raises() -> None:
    """未知の軸 key は KeyError（握りつぶさない）。"""
    base = _make_dummy()
    with pytest.raises(KeyError):
        apply_axes({"bogus": 0.5}, base)
