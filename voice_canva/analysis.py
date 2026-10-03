"""声のCanva (Voice Designer) — Step 0/1: 音声パラメータ抽出パイプライン。

実在話者のクリーン録音 wav から、以下を抽出して :class:`SpeakerFeatures` にまとめる。

- pyworld: F0 / スペクトル包絡(SP) / 非周期性(AP)（フレーム単位、再合成可能な生パラメータ）
- parselmouth(Praat): フォルマント F1..F4・jitter(local)・shimmer(local)・HNR・
  スペクトル傾斜（軸マッピングの相関分析と ±2σ 可動域算出に使うスカラ統計）

設計指針（memo §2.1〜2.3, §5）:
- 生パラメータ（F0/SP/AP）は再合成エンジンの素材として保持し、UI には直接出さない。
- スカラ統計は軸→パラメータ変換の相関構造と可動域（±2σ）を支える材料。

重い依存（pyworld / parselmouth / librosa）は、未インストール環境でも本モジュールの
import 時にクラッシュしないよう、すべて関数内 import とする。
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

import numpy as np

from voice_canva import config


# ---------------------------------------------------------------------------
# データ型（INTERFACES.md のコントラクト）
# ---------------------------------------------------------------------------
@dataclass
class SpeakerFeatures:
    """1 話者ぶんの抽出特徴量。

    配列（f0/sp/ap/formants）は再合成・ワーピングの素材、スカラ統計は
    軸マッピングの相関分析と ±2σ 可動域算出に使う。
    """

    name: str                 # 話者ID
    sr: int                   # サンプルレート (= config.DEFAULT_SR)
    frame_period: float       # = config.FRAME_PERIOD
    f0: np.ndarray            # (T,)   フレーム単位 F0 [Hz]
    sp: np.ndarray            # (T, F) スペクトル包絡 (pyworld cheaptrick)
    ap: np.ndarray            # (T, F) 非周期性 (pyworld d4c)
    # parselmouth 由来のスカラ統計
    f0_mean: float            # 有声フレームの平均 F0 [Hz]
    f0_std: float             # 有声フレームの F0 標準偏差（安定性の逆指標）
    formants: np.ndarray      # (4,) F1..F4 平均 [Hz]
    jitter: float             # local jitter（無次元、周期ゆらぎ）
    shimmer: float            # local shimmer（無次元、振幅ゆらぎ）
    hnr: float                # Harmonics-to-Noise Ratio [dB]
    spectral_tilt: float      # スペクトル傾斜 [dB/oct]

    # -- 保存/読み込み ------------------------------------------------------
    @staticmethod
    def _base_path(path: str) -> str:
        """`path` から拡張子（.npz/.json）を除いた基底パスを返す。"""
        root, ext = os.path.splitext(path)
        if ext.lower() in (".npz", ".json"):
            return root
        return path

    def save(self, path: str) -> None:
        """配列を ``<base>.npz`` に、スカラを ``<base>.json`` に保存する。

        `path` は拡張子の有無いずれでも受け付け、同名で .npz と .json を併置する。
        """
        base = self._base_path(path)
        out_dir = os.path.dirname(base)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        np.savez(
            base + ".npz",
            f0=np.asarray(self.f0, dtype=np.float64),
            sp=np.asarray(self.sp, dtype=np.float64),
            ap=np.asarray(self.ap, dtype=np.float64),
            formants=np.asarray(self.formants, dtype=np.float64),
        )

        scalars = {
            "name": self.name,
            "sr": int(self.sr),
            "frame_period": float(self.frame_period),
            "f0_mean": float(self.f0_mean),
            "f0_std": float(self.f0_std),
            "jitter": float(self.jitter),
            "shimmer": float(self.shimmer),
            "hnr": float(self.hnr),
            "spectral_tilt": float(self.spectral_tilt),
        }
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(scalars, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "SpeakerFeatures":
        """``<base>.npz`` と ``<base>.json`` から特徴量を復元する。"""
        base = cls._base_path(path)
        with np.load(base + ".npz") as arrs:
            f0 = arrs["f0"]
            sp = arrs["sp"]
            ap = arrs["ap"]
            formants = arrs["formants"]
        with open(base + ".json", "r", encoding="utf-8") as f:
            s = json.load(f)
        return cls(
            name=str(s["name"]),
            sr=int(s["sr"]),
            frame_period=float(s["frame_period"]),
            f0=f0,
            sp=sp,
            ap=ap,
            f0_mean=float(s["f0_mean"]),
            f0_std=float(s["f0_std"]),
            formants=formants,
            jitter=float(s["jitter"]),
            shimmer=float(s["shimmer"]),
            hnr=float(s["hnr"]),
            spectral_tilt=float(s["spectral_tilt"]),
        )


# ---------------------------------------------------------------------------
# 内部ヘルパ
# ---------------------------------------------------------------------------
def _load_mono(path: str, sr: int) -> np.ndarray:
    """librosa で `sr` にリサンプル・モノラル化した float64 波形を返す。

    pyworld / parselmouth はいずれも float64・C 連続配列を前提とするため、
    ここで型と連続性を保証する。
    """
    import librosa

    audio, _ = librosa.load(path, sr=sr, mono=True)
    return np.ascontiguousarray(audio, dtype=np.float64)


def _repair_octave_jumps(
    f0: np.ndarray, window: int = 7, max_semitones: float = 6.0
) -> np.ndarray:
    """F0 のオクターブ誤り（倍・半分の取り違え）を局所中央値基準で補正する。

    歌声など高起伏な信号では harvest が隣接フレームでオクターブ跳びを起こし、合成の
    土台にすると音程が暴れる。有声フレームの log2(F0) について**局所中央値**を求め、
    そこから 1 オクターブ近く外れた孤立フレームのみを、最も近いオクターブへ寄せ直す。
    局所基準にすることで、自然なビブラート・抑揚や、声域が広い箇所での正当な変化を
    壊さずに、誤り由来のスパイクだけを潰す（グローバル中央値だと広域変化を誤補正する）。
    """
    f0 = np.asarray(f0, dtype=np.float64).copy()
    voiced = f0 > 0.0
    n_voiced = int(np.count_nonzero(voiced))
    if n_voiced < max(3, window):
        return f0

    from scipy.ndimage import median_filter

    log2f = np.log2(f0[voiced])
    local_med = median_filter(log2f, size=window, mode="nearest")
    deviation = log2f - local_med
    # 局所中央値から「最も近いオクターブ」へ何オクターブ寄せるか（整数）。
    shifts = np.round(deviation)
    thresh = max_semitones / 12.0
    correct = (shifts != 0) & (np.abs(deviation) > (0.5 + thresh))
    if np.any(correct):
        log2f[correct] = log2f[correct] - shifts[correct]
        f0_v = f0[voiced]
        f0_v[correct] = 2.0 ** log2f[correct]
        f0[voiced] = f0_v
    return f0


def _extract_world(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """pyworld で F0/SP/AP を抽出する（話者適応 F0 レンジ + オクターブ補正）。

    1 パス目に広いレンジで F0 を粗推定し、その中央値から話者適応の探索レンジを定めて
    2 パス目を実行する。これにより高音・低音話者でのオクターブ誤り（半分/倍の取り違え）を
    抑制する。残るオクターブ跳びは :func:`_repair_octave_jumps` で補正する。フレーム周期と
    レンジ上下限は config を単一情報源として用いる。
    """
    import pyworld as pw

    # --- パス1: 広レンジで粗推定 ---
    f0_rough, t = pw.harvest(
        x, sr,
        f0_floor=config.F0_FLOOR,
        f0_ceil=config.F0_CEIL,
        frame_period=config.FRAME_PERIOD,
    )
    voiced = f0_rough > 0.0

    # --- パス2: 話者適応レンジ（中央値の 0.5〜2.0 倍域）で再推定 ---
    if np.count_nonzero(voiced) >= 3:
        med = float(np.median(f0_rough[voiced]))
        floor = max(config.F0_FLOOR, med * 0.5)
        ceil = min(config.F0_CEIL, med * 2.0)
        if ceil > floor:
            f0, t = pw.harvest(
                x, sr, f0_floor=floor, f0_ceil=ceil,
                frame_period=config.FRAME_PERIOD,
            )
        else:
            f0 = f0_rough
    else:
        f0 = f0_rough

    f0 = pw.stonemask(x, f0, t, sr)
    f0 = _repair_octave_jumps(f0)
    sp = pw.cheaptrick(x, f0, t, sr, f0_floor=config.F0_FLOOR)
    ap = pw.d4c(x, f0, t, sr)
    return f0, sp, ap


def _spectral_tilt(x: np.ndarray, sr: int) -> float:
    """長時間平均スペクトルの傾きを線形回帰で求め dB/oct を返す。

    Welch 法で平均パワースペクトル密度を推定し、周波数を log2 軸（オクターブ）に取って
    dB = a*log2(f)+b を最小二乗で当てはめ、傾き a を「スペクトル傾斜 [dB/oct]」とする
    （負＝高域減衰）。Praat の Ltas per-bin クエリは版差でコマンド名が不安定なため、
    numpy/scipy で信号から直接算出して環境依存を排除する。
    """
    from scipy.signal import welch

    nperseg = min(2048, len(x))
    if nperseg < 16:
        return 0.0
    freqs, psd = welch(x, fs=sr, nperseg=nperseg)

    # 直流〜超低域と Nyquist 近傍を除外（log2/対数化の破綻と帯域端の歪みを避ける）。
    lo = 100.0
    hi = 0.9 * (sr / 2.0)
    mask = (freqs >= lo) & (freqs <= hi) & (psd > 0.0) & np.isfinite(psd)
    if int(np.count_nonzero(mask)) < 2:
        return 0.0

    log2_f = np.log2(freqs[mask])
    db = 10.0 * np.log10(psd[mask])
    slope, _intercept = np.polyfit(log2_f, db, 1)
    return float(slope) if np.isfinite(slope) else 0.0


def _extract_praat(
    x: np.ndarray, sr: int
) -> tuple[np.ndarray, float, float, float, float]:
    """parselmouth でフォルマント・jitter・shimmer・HNR・スペクトル傾斜を抽出する。

    戻り値: (formants(4,), jitter_local, shimmer_local, hnr_db, spectral_tilt)
    """
    import parselmouth
    from parselmouth.praat import call

    sound = parselmouth.Sound(x, sampling_frequency=float(sr))
    f0min = float(config.F0_FLOOR)
    f0max = float(config.F0_CEIL)

    # --- フォルマント F1..F4 平均（Burg 法） ---------------------------------
    # 最大フォルマント周波数は声道帯域の慣用値 5500 Hz（成人混在を想定）。
    formant = call(sound, "To Formant (burg)", 0.0, 5.0, 5500.0, 0.025, 50.0)
    formants_list: list[float] = []
    for i in range(1, 5):
        val = call(formant, "Get mean", i, 0.0, 0.0, "hertz")
        formants_list.append(float(val) if val is not None and np.isfinite(val) else 0.0)
    formants = np.asarray(formants_list, dtype=np.float64)

    # --- jitter / shimmer（PointProcess 経由の local 指標） -----------------
    point_process = call(sound, "To PointProcess (periodic, cc)", f0min, f0max)
    jitter = call(
        point_process, "Get jitter (local)", 0.0, 0.0, 1e-4, 0.02, 1.3
    )
    shimmer = call(
        [sound, point_process], "Get shimmer (local)", 0.0, 0.0, 1e-4, 0.02, 1.3, 1.6
    )

    # --- HNR（Harmonicity, cc 法の平均） ------------------------------------
    harmonicity = call(sound, "To Harmonicity (cc)", 0.01, f0min, 0.1, 1.0)
    hnr = call(harmonicity, "Get mean", 0.0, 0.0)

    # --- スペクトル傾斜 ------------------------------------------------------
    tilt = _spectral_tilt(x, sr)

    def _f(v: float) -> float:
        return float(v) if v is not None and np.isfinite(v) else 0.0

    return formants, _f(jitter), _f(shimmer), _f(hnr), tilt


# ---------------------------------------------------------------------------
# 公開 API（INTERFACES.md のシグネチャ厳守）
# ---------------------------------------------------------------------------
def analyze_wav(
    path: str, name: str | None = None, sr: int = config.DEFAULT_SR
) -> SpeakerFeatures:
    """1 つの wav を分析し :class:`SpeakerFeatures` を返す。

    Args:
        path: 入力 wav のパス。
        name: 話者ID。None ならファイル名（拡張子なし）を採用する。
        sr: 処理サンプルレート（既定 config.DEFAULT_SR にリサンプル）。

    Returns:
        抽出済みの SpeakerFeatures。
    """
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]

    x = _load_mono(path, sr)
    f0, sp, ap = _extract_world(x, sr)

    voiced = f0[f0 > 0.0]
    f0_mean = float(np.mean(voiced)) if voiced.size > 0 else 0.0
    f0_std = float(np.std(voiced)) if voiced.size > 0 else 0.0

    formants, jitter, shimmer, hnr, spectral_tilt = _extract_praat(x, sr)

    return SpeakerFeatures(
        name=name,
        sr=int(sr),
        frame_period=float(config.FRAME_PERIOD),
        f0=f0,
        sp=sp,
        ap=ap,
        f0_mean=f0_mean,
        f0_std=f0_std,
        formants=formants,
        jitter=jitter,
        shimmer=shimmer,
        hnr=hnr,
        spectral_tilt=spectral_tilt,
    )


def analyze_dir(
    data_dir: str = config.PATHS.data_dir, out_dir: str = config.PATHS.features_dir
) -> list[SpeakerFeatures]:
    """`data_dir` 内の全 *.wav を分析し、`out_dir` に保存してリストで返す。

    各話者は ``<out_dir>/<name>.npz`` + ``<out_dir>/<name>.json`` として保存される。

    Args:
        data_dir: 入力 wav 置き場。
        out_dir: 特徴量（npz/json）の保存先。

    Returns:
        分析した SpeakerFeatures のリスト（ファイル名昇順）。
    """
    os.makedirs(out_dir, exist_ok=True)
    wav_paths = sorted(glob.glob(os.path.join(data_dir, "*.wav")))

    results: list[SpeakerFeatures] = []
    for wav_path in wav_paths:
        feat = analyze_wav(wav_path)
        feat.save(os.path.join(out_dir, feat.name + ".npz"))
        results.append(feat)
    return results
