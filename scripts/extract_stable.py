"""話者録音から「安定した発話区間」をアンカーとして抽出する（旧方式。現行は seedvc/select_anchors.py）。

従来の最大音量基準は感情的/叫び気味の区間(高F0・大抑揚・低HNR)を拾いがちだった。
本スクリプトは F0 の安定性・有声率・有声確度で評価し、落ち着いてクリアに喋っている
区間を選ぶ。各話者の 4s(分析用) と 12s(VCターゲット用) を data/ に書き出す。
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")
import librosa
import numpy as np
import soundfile as sf
import sys

SR16 = 16000
N_CANDIDATES = 40   # ファイル全体に等間隔で評価する窓数


def _score_window(seg16: np.ndarray) -> dict | None:
    """4s窓の安定性を評価。落ち着いた発話ほど高スコア。"""
    f0, vflag, vprob = librosa.pyin(seg16, fmin=70, fmax=500, sr=SR16,
                                    frame_length=1024, hop_length=256)
    voiced = ~np.isnan(f0)
    vr = float(np.mean(voiced))
    if vr < 0.4 or vr > 0.92:           # 無声過多 or 連続母音すぎを除外
        return None
    fv = f0[voiced]
    if len(fv) < 10:
        return None
    # F0 安定性: 隣接フレームの半音変動の中央値（小さい=落ち着いた発話）
    semi = np.abs(np.diff(np.log2(fv))) * 12.0
    instab = float(np.median(semi))
    conf = float(np.nanmean(vprob[voiced]))   # 有声確度（周期性の明瞭さ）
    f0med = float(np.median(fv))
    # スコア: 確度高・不安定低を優先。極端な高F0は軽く減点。
    hi_pen = max(0.0, (f0med - 350.0) / 350.0)
    score = conf / (1.0 + instab) - 0.15 * hi_pen
    return dict(score=score, instab=instab, conf=conf, vr=vr, f0=f0med)


def main() -> int:
    """使い方: python scripts/extract_stable.py <話者1.wav> <話者2.wav> ...（spk1, spk2, ... の順に採番）"""
    srcs = sys.argv[1:]
    if not srcs:
        print(main.__doc__, flush=True)
        return 1
    for i, path in enumerate(srcs, 1):
        name = f"spk{i}"
        y, sr = sf.read(path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        y16 = librosa.resample(y, orig_sr=sr, target_sr=SR16)
        win = int(4.0 * SR16)
        guard = int(5 * SR16)
        positions = np.linspace(guard, len(y16) - guard - win, N_CANDIDATES).astype(int)
        best = None
        for p in positions:
            seg = y16[p:p + win]
            if float(np.max(np.abs(seg))) < 1e-3:
                continue
            m = _score_window(seg)
            if m is None:
                continue
            if best is None or m["score"] > best["score"]:
                best = {**m, "pos16": p}
        if best is None:
            print(f"{name}: 安定候補なし", flush=True)
            continue
        # 元srでの位置に換算して 4s と 12s を切り出す（12sは安定窓を中心に拡張）
        center = best["pos16"] / SR16
        for ws, out in [(4.0, f"data/{name}.wav"), (12.0, f"data/tgt_{name}_long.wav")]:
            half = ws / 2.0
            start = max(0.0, center + 2.0 - half)   # 4s窓の中心付近に揃える
            i = int(start * sr)
            seg = y[i:i + int(ws * sr)]
            seg = seg / (np.max(np.abs(seg)) + 1e-9) * 0.9
            sf.write(out, seg.astype("float32"), sr, subtype="PCM_16")
        print(f"{name}: @{center:.0f}s 不安定={best['instab']:.2f}半音 確度={best['conf']:.2f} "
              f"有声={best['vr']:.2f} F0={best['f0']:.0f}Hz", flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
