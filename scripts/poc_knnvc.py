"""kNN-VC PoC: 日本語の発音(訛り)を保ったまま別人/中間声へ変換できるか検証。

FreeVC は英語学習で「外人っぽさ」が出た。kNN-VC は WavLM 特徴空間で
**ソースの各フレームに最も近いターゲットの実フレームを検索して貼る**非パラメトリック方式。
ソースの調音がそのまま残るため、日本語の発音が保たれやすい。

- 第1段階: 単一ターゲット変換（spk3 → spk4）。FreeVC 版と訛りを比較。
- 第2段階: 2 話者(spk4, spk2)それぞれの matching set で kNN 検索し、取得特徴を
  ベクトル補間 → 実在しない中間声（素材混合でなく特徴補間）。

実行: .venv-vc/bin/python scripts/poc_knnvc.py   （CPU。torch.hub で初回DLあり）
出力: output/vc/knn_*.wav（16kHz）
"""
from __future__ import annotations

import os

import numpy as np
import soundfile as sf
import torch

OUT = "output/vc"
TOPK = 4


def _load():
    knn_vc = torch.hub.load(
        "bshall/knn-vc", "knn_vc",
        prematched=True, trust_repo=True, pretrained=True, device="cpu",
    )
    return knn_vc


def _save(wav: torch.Tensor, path: str, sr: int = 16000) -> None:
    arr = wav.detach().cpu().float().numpy().reshape(-1)
    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak > 0.97:
        arr = arr * (0.97 / peak)
    sf.write(path, arr.astype(np.float32), sr)


def _interp_match(knn_vc, query: torch.Tensor, set_a: torch.Tensor,
                  set_b: torch.Tensor, w: float, topk: int = TOPK) -> torch.Tensor:
    """各クエリフレームについて set_a と set_b で kNN 検索し、取得平均特徴を w で補間。

    出力 = (1-w)*meanKNN_A + w*meanKNN_B をボコーダで波形化。これにより 2 話者の
    間の整合した中間声になる（フレーム毎にどちらか一方へ切替わるのを避ける）。
    """
    def knn_mean(qs: torch.Tensor, ms: torch.Tensor) -> torch.Tensor:
        # コサイン距離（L2正規化して内積）で topk 近傍を平均。
        qn = torch.nn.functional.normalize(qs, dim=-1)
        mn = torch.nn.functional.normalize(ms, dim=-1)
        sim = qn @ mn.T                      # (Tq, Tm)
        idx = sim.topk(min(topk, ms.shape[0]), dim=-1).indices  # (Tq, k)
        gathered = ms[idx]                   # (Tq, k, D)
        return gathered.mean(dim=1)          # (Tq, D)

    feat_a = knn_mean(query, set_a)
    feat_b = knn_mean(query, set_b)
    feat = (1.0 - w) * feat_a + w * feat_b
    return knn_vc.vocode(feat[None].to(torch.float32))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    knn_vc = _load()

    src = "data/spk3.wav"
    q = knn_vc.get_features(src)

    # --- 第1段階: 単一ターゲット変換 ---
    for tag, tgt in [("spk4", "data/tgt_spk4_long.wav"), ("spk2", "data/tgt_spk2_long.wav")]:
        ms = knn_vc.get_matching_set([tgt])
        out = knn_vc.match(q, ms, topk=TOPK)
        _save(out, f"{OUT}/knn_to_{tag}.wav")
        print(f"[knn] to_{tag}: matching_set={tuple(ms.shape)} -> {OUT}/knn_to_{tag}.wav")

    # --- 第2段階: 2話者の特徴補間 = 中間声 ---
    set_a = knn_vc.get_matching_set(["data/tgt_spk4_long.wav"])
    set_b = knn_vc.get_matching_set(["data/tgt_spk2_long.wav"])
    for w in (0.0, 0.5, 1.0):
        out = _interp_match(knn_vc, q, set_a, set_b, w)
        _save(out, f"{OUT}/knn_interp_{int(w * 100):03d}.wav")
        print(f"[knn] interp spk4->spk2 w={w}: {OUT}/knn_interp_{int(w * 100):03d}.wav")

    print("[knn] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
