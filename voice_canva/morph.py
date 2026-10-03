"""声のCanva — 話者モーフィング（2 人の実在話者アンカー間の補間）。

memo §2.2 のアンカー設計を本来の形で実装する。抽象 6 軸（単一話者の加工）では
「同一話者の変形」にしか聞こえないため、本モジュールは **2 人の実在話者を端点に据え、
その間を補間**して中間の声を生成する。各次元（高さ／声色／気息／粗さ）を独立に補間でき、
「二人の違いがどのパラメータに宿るか」を直感的に編集できる。

中核アイデア:
- 話者の同一性を最も強く決めるのは **平均スペクトル包絡の形（フォルマント配置・声色）**。
  これを 2 話者の平均 dB スペクトル差として求め、ベース発話の各フレームへ適用して
  音色を相手話者へ寄せる（energy 保存でラウドネスは不変）。
- ベース発話（src 話者の録音）の音韻内容・タイミングはそのまま使う。位置合わせ不要で
  「src の発話内容を dst の声で喋らせた」声になる。weight=0 で src を厳密に再現する。

依存は numpy のみ。SpeakerFeatures は型注釈のみで参照（重い依存を巻き込まない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from voice_canva import config

if TYPE_CHECKING:  # 実行時 import しない
    from voice_canva.analysis import SpeakerFeatures


__all__ = [
    "MorphDim",
    "MORPH_DIMS",
    "SpeakerTimbre",
    "speaker_timbre",
    "blend_timbres",
    "default_weights",
    "uniform_weights",
    "morph",
]


# ---------------------------------------------------------------------------
# 補間の安全パラメータ
# ---------------------------------------------------------------------------
_SP_FLOOR: float = 1e-12
# 声色（スペクトル包絡差）の per-bin 利得上限 [dB]。単一ビンの暴走＝割れを防ぐ。
_MAX_COLOR_GAIN_DB: float = 15.0
# 気息ハスキー側で高域 AP に与える床の下限周波数 [Hz]。
_BREATH_HF_HZ: float = 2000.0
# 粗さ摂動の安全上限（相対）。memo §5「やりすぎ＝別人化／機械臭」を踏まえる。
_MAX_JITTER_REL: float = 0.05
_MAX_SHIMMER_REL: float = 0.20
# 摂動の決定論シード（操作のたびに音が変わらないよう固定）。
_PERTURB_SEED: int = 20240628


# ---------------------------------------------------------------------------
# 補間次元（UI スライダー）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MorphDim:
    key: str
    label: str
    description: str


# 0.0 = src 話者そのまま、1.0 = dst 話者の特性へ。中間値で補間（0.5＝真の中間）。
MORPH_DIMS: tuple[MorphDim, ...] = (
    MorphDim("pitch", "声の高さ", "F0（基本周波数）を相手話者の平均へ寄せる"),
    MorphDim("color", "声色", "平均スペクトル包絡（フォルマント配置・音色）を相手へ寄せる＝同一性の主因"),
    MorphDim("breath", "気息", "非周期成分（息っぽさ／HNR）を相手へ寄せる"),
    MorphDim("roughness", "粗さ", "jitter/shimmer（ゆらぎ・かすれ）を相手へ寄せる"),
)

MORPH_KEYS: tuple[str, ...] = tuple(d.key for d in MORPH_DIMS)


# ---------------------------------------------------------------------------
# 話者の音色シグネチャ
# ---------------------------------------------------------------------------
@dataclass
class SpeakerTimbre:
    """1 話者の「声らしさ」を要約した補間用シグネチャ。"""

    name: str
    sr: int
    n_bins: int
    f0_log2: float          # log2(有声 F0 平均)
    avg_db: np.ndarray      # (F,) 有声平均 dB スペクトル（周波数方向にゼロ平均＝形のみ）
    ap_mean: float          # 有声平均 非周期性 [0,1]
    jitter: float
    shimmer: float


def speaker_timbre(feats: "SpeakerFeatures") -> SpeakerTimbre:
    """SpeakerFeatures から補間用の音色シグネチャを抽出する。"""
    f0 = np.asarray(feats.f0, dtype=np.float64)
    sp = np.asarray(feats.sp, dtype=np.float64)
    ap = np.asarray(feats.ap, dtype=np.float64)
    voiced = f0 > 0.0
    if not np.any(voiced):
        voiced = np.ones_like(f0, dtype=bool)

    f0v = f0[voiced]
    f0_log2 = float(np.log2(np.mean(f0v))) if np.mean(f0v) > 0 else 0.0

    # 有声平均 dB スペクトル → 周波数方向にゼロ平均（全体レベルを除き「形」だけにする）。
    sp_db = 10.0 * np.log10(np.maximum(sp[voiced], _SP_FLOOR))
    avg_db = sp_db.mean(axis=0)
    avg_db = avg_db - float(avg_db.mean())

    ap_mean = float(np.clip(ap[voiced], 0.0, 1.0).mean())

    return SpeakerTimbre(
        name=feats.name,
        sr=int(feats.sr),
        n_bins=int(sp.shape[1]),
        f0_log2=f0_log2,
        avg_db=avg_db,
        ap_mean=ap_mean,
        jitter=float(feats.jitter),
        shimmer=float(feats.shimmer),
    )


# ---------------------------------------------------------------------------
# 複数話者アンカーの重み付きブレンド（N 話者の声空間）
# ---------------------------------------------------------------------------
def blend_timbres(
    timbres: list[SpeakerTimbre], weights: list[float] | None = None
) -> SpeakerTimbre:
    """複数話者の音色シグネチャを重み付き平均し、1 つの「重心声」を作る。

    memo §2.2「生成声は実在声間の補間として位置づく」を N 話者へ一般化する。重みは
    総和 1 へ正規化（バリセントリック座標）。avg_db は各々が周波数方向ゼロ平均の「形」
    なので、重み和 1 の線形結合もゼロ平均の妥当な中間スペクトルになる。

    Args:
        timbres: アンカー話者のシグネチャ（1 つ以上、同一 sr・n_bins）。
        weights: 各アンカーの重み（None で均等）。負値は不可（[0,∞) にクリップ）。

    Returns:
        ブレンド結果の :class:`SpeakerTimbre`（name="blend"）。
    """
    if not timbres:
        raise ValueError("blend_timbres: timbres が空です")
    n = len(timbres)
    if weights is None:
        weights = [1.0] * n
    if len(weights) != n:
        raise ValueError("blend_timbres: weights の数が timbres と一致しません")

    n_bins = timbres[0].n_bins
    sr = timbres[0].sr
    for t in timbres:
        if t.n_bins != n_bins or t.sr != sr:
            raise ValueError("blend_timbres: sr / n_bins が話者間で不一致です")

    w = np.clip(np.asarray(weights, dtype=np.float64), 0.0, None)
    total = float(w.sum())
    if total <= 0.0:
        w = np.full(n, 1.0 / n)
    else:
        w = w / total

    avg_db = np.zeros(n_bins, dtype=np.float64)
    f0_log2 = ap_mean = jitter = shimmer = 0.0
    for wi, t in zip(w, timbres):
        avg_db += wi * t.avg_db
        f0_log2 += wi * t.f0_log2
        ap_mean += wi * t.ap_mean
        jitter += wi * t.jitter
        shimmer += wi * t.shimmer

    return SpeakerTimbre(
        name="blend",
        sr=sr,
        n_bins=n_bins,
        f0_log2=float(f0_log2),
        avg_db=avg_db,
        ap_mean=float(ap_mean),
        jitter=float(jitter),
        shimmer=float(shimmer),
    )


# ---------------------------------------------------------------------------
# 重み（各次元の補間量 0..1）
# ---------------------------------------------------------------------------
def default_weights() -> dict[str, float]:
    """全次元 0.0（= src 話者そのまま）。"""
    return {k: 0.0 for k in MORPH_KEYS}


def uniform_weights(alpha: float) -> dict[str, float]:
    """全次元を同一の ``alpha`` に揃える（真の話者間補間。0.5＝中間の声）。"""
    a = float(alpha)
    return {k: a for k in MORPH_KEYS}


def _resolve_weights(weights: dict[str, float] | float | None) -> dict[str, float]:
    if weights is None:
        return default_weights()
    if isinstance(weights, (int, float)):
        return uniform_weights(float(weights))
    resolved = default_weights()
    for k, v in weights.items():
        if k not in resolved:
            raise KeyError(f"morph: 未知の補間次元 key: {k!r}")
        # 端点外への軽い外挿も許す（誇張）。安全上 [-0.5, 1.5] に制限。
        resolved[k] = float(np.clip(v, -0.5, 1.5))
    return resolved


# ---------------------------------------------------------------------------
# モーフィング本体
# ---------------------------------------------------------------------------
def morph(
    base: "SpeakerFeatures",
    src: SpeakerTimbre,
    dst: SpeakerTimbre,
    weights: dict[str, float] | float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ベース発話 ``base`` の音韻内容を保ったまま、音色を ``src`` から ``dst`` へ補間する。

    Args:
        base: 音韻内容・タイミングを供給する土台（通常 ``src`` 話者の録音）。
        src: 端点 0 側の音色シグネチャ（``base`` の話者）。
        dst: 端点 1 側の音色シグネチャ（寄せたい相手話者）。
        weights: 次元 key → 補間量（0=src, 1=dst）。float を渡すと全次元一律（=話者ブレンド）。
            None で src そのまま。

    Returns:
        ``(f0_mod, sp_mod, ap_mod)``。pyworld.synthesize に渡せる float64・C 連続。
    """
    w = _resolve_weights(weights)

    f0 = np.array(base.f0, dtype=np.float64, copy=True)      # (T,)
    sp = np.array(base.sp, dtype=np.float64, copy=True)      # (T, F)
    ap = np.array(base.ap, dtype=np.float64, copy=True)      # (T, F)
    n_frames, n_bins = sp.shape
    sr = int(base.sr)
    freqs = np.linspace(0.0, sr / 2.0, n_bins)
    voiced = f0 > 0.0
    rng = np.random.default_rng(_PERTURB_SEED)

    # -- (1) 声の高さ: F0 平均を log 領域で補間（破綻ガードレールで制限）--------
    # 同一性の大半は声色（声道）にあり絶対ピッチではない。WORLD は大きな上方シフトで
    # 破綻するため、適用半音量を ±config の上限に物理制限する（memo §2.3）。声色は
    # 別途フル補間できるので「相手の声色＋破綻しない高さ」を作れる。
    if np.any(voiced) and abs(w["pitch"]) > 1e-9:
        d_semitones = (dst.f0_log2 - src.f0_log2) * 12.0 * w["pitch"]
        d_semitones = float(np.clip(
            d_semitones,
            -config.MAX_PITCH_DOWN_SEMITONES,
            config.MAX_PITCH_UP_SEMITONES,
        ))
        f0[voiced] = f0[voiced] * (2.0 ** (d_semitones / 12.0))

    # -- (2) 声色: 平均 dB スペクトル差を適用（同一性の主因）-----------------
    # base の各フレーム包絡へ、相手話者との平均スペクトル形の差を w 倍で重畳する。
    if src.n_bins == dst.n_bins == n_bins and abs(w["color"]) > 1e-9:
        diff_db = (dst.avg_db - src.avg_db) * w["color"]
        gain_db = np.clip(diff_db, -_MAX_COLOR_GAIN_DB, _MAX_COLOR_GAIN_DB)
        e_before = sp.sum(axis=1, keepdims=True)
        sp = sp * (10.0 ** (gain_db / 10.0))[None, :]
        # energy 保存（声色＝音色変化であってラウドネスは変えない。割れ防止）。
        e_after = sp.sum(axis=1, keepdims=True)
        scale = np.divide(e_before, e_after, out=np.ones_like(e_before), where=e_after > 0.0)
        sp = sp * scale

    # -- (3) 気息: 非周期性 AP の平均レベルを相手へ寄せる --------------------
    d_ap = (dst.ap_mean - src.ap_mean) * w["breath"]
    if abs(d_ap) > 1e-9:
        ap = np.clip(ap + d_ap, 0.0, 1.0)
        # 息っぽく寄せる側（AP 増）は高域に床を与えて気息感を補強。
        if d_ap > 0.0 and np.any(voiced):
            hf = freqs >= _BREATH_HF_HZ
            if np.any(hf):
                floor = min(d_ap, 1.0)
                block = ap[np.ix_(voiced, hf)]
                ap[np.ix_(voiced, hf)] = np.maximum(block, floor)

    # -- (4) 粗さ: jitter（F0 ゆらぎ）+ shimmer（振幅ゆらぎ）を相手へ寄せる ---
    if np.any(voiced):
        d_jit = float(np.clip(max(0.0, (dst.jitter - src.jitter) * w["roughness"]), 0.0, _MAX_JITTER_REL))
        if d_jit > 0.0:
            pert = rng.standard_normal(int(np.count_nonzero(voiced)))
            f0[voiced] = f0[voiced] * np.clip(1.0 + d_jit * pert, 1e-3, None)
        d_shim = float(np.clip(max(0.0, (dst.shimmer - src.shimmer) * w["roughness"]), 0.0, _MAX_SHIMMER_REL))
        if d_shim > 0.0:
            amp = np.clip(1.0 + d_shim * rng.standard_normal(n_frames), 1e-3, None)
            amp = np.where(voiced, amp, 1.0)
            sp = sp * (amp ** 2)[:, None]

    sp = np.maximum(sp, _SP_FLOOR)
    return (
        np.ascontiguousarray(f0, dtype=np.float64),
        np.ascontiguousarray(sp, dtype=np.float64),
        np.ascontiguousarray(ap, dtype=np.float64),
    )
