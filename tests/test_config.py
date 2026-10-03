"""config（Single Source of Truth）の軽量検証。

重い依存（pyworld / parselmouth / librosa 等）を一切 import せず、定数・軸定義の
不変条件のみを pytest で検証する（memo §2.2 の 6 軸契約 / INTERFACES.md）。
"""
from __future__ import annotations

import pytest

from voice_canva import config


def test_axes_has_six() -> None:
    """UI に見せる軸はちょうど 6 本（memo §2.2）。"""
    assert len(config.AXES) == 6


def test_axis_keys_match_axes() -> None:
    """AXIS_KEYS は AXES の key を順序どおり写したもの。"""
    assert config.AXIS_KEYS == tuple(a.key for a in config.AXES)
    assert len(config.AXIS_KEYS) == 6


def test_axis_keys_unique() -> None:
    """軸 key は一意（重複した連動定義を防ぐ）。"""
    assert len(set(config.AXIS_KEYS)) == len(config.AXIS_KEYS)


def test_axis_by_key_returns_matching_axis() -> None:
    """axis_by_key は key 一致の Axis を返す。"""
    for key in config.AXIS_KEYS:
        axis = config.axis_by_key(key)
        assert axis.key == key
        assert isinstance(axis, config.Axis)


def test_axis_by_key_unknown_raises() -> None:
    """未知 key は KeyError（黙って既定値に倒さない＝握りつぶし禁止）。"""
    with pytest.raises(KeyError):
        config.axis_by_key("nonexistent_axis")


def test_each_axis_is_well_formed() -> None:
    """各軸はラベル・端点・連動パラメータを必ず備える。"""
    for axis in config.AXES:
        assert axis.key
        assert axis.label
        assert axis.low
        assert axis.high
        assert axis.low != axis.high
        assert len(axis.linked_params) >= 1
        assert all(isinstance(p, str) and p for p in axis.linked_params)


def test_axis_value_range_is_symmetric_unit() -> None:
    """正規化レンジは AXIS_MIN < 0 < AXIS_MAX で 0 を中央に持つ。"""
    assert config.AXIS_MIN < 0.0 < config.AXIS_MAX
    assert config.AXIS_MIN == pytest.approx(-config.AXIS_MAX)


def test_signal_constants_are_sane() -> None:
    """信号処理の基本定数が妥当な範囲にある。"""
    assert config.DEFAULT_SR > 0
    assert config.FRAME_PERIOD > 0.0
    assert 0.0 < config.F0_FLOOR < config.F0_CEIL
    assert config.SIGMA_CLIP > 0.0
