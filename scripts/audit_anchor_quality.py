"""全アンカーの参照音声(tgt_spk*_long.wav)を無参照品質メトリクス(Torchaudio SQUIM)で採点する。

SQUIM_OBJECTIVE は参照不要で PESQ/STOI/SI-SDR を推定する。録音のクリーンさ(ノイズ/歪み)を
反映する PESQ 推定を主指標に、アンカーの品質を採点・ランキングし data/anchor_quality.json に保存。

用途: 低品質アンカーの除外判断、および select_anchors.py の品質ゲートのしきい値決定。
"""
from __future__ import annotations

import glob
import json
import os
import warnings

warnings.filterwarnings("ignore")
import librosa
import numpy as np
import torch
import torchaudio
from torchaudio.pipelines import SQUIM_OBJECTIVE

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(PROJ, "data", "anchor_quality.json")


def _label(name, src):
    if name in src:
        return src[name].replace("_128k.wav", "").replace(".wav", "").split("_")[0]
    return name


def main() -> int:
    src = {}
    p = os.path.join(PROJ, "data", "anchor_sources.json")
    if os.path.exists(p):
        src = json.load(open(p, encoding="utf-8"))

    model = SQUIM_OBJECTIVE.get_model()
    model.eval()

    rows = []
    for w in glob.glob(os.path.join(PROJ, "data", "tgt_spk*_long.wav")):
        name = os.path.basename(w).replace("tgt_", "").replace("_long.wav", "")
        y = librosa.load(w, sr=16000, mono=True)[0]
        yt = torch.tensor(y).unsqueeze(0).float()
        with torch.inference_mode():
            stoi, pesq, sisdr = model(yt)
        rows.append({
            "name": name, "label": _label(name, src),
            "pesq": float(pesq.item()), "stoi": float(stoi.item()), "si_sdr": float(sisdr.item()),
        })

    rows.sort(key=lambda r: r["pesq"])  # 低品質(PESQ小)が先頭
    scores = {r["name"]: r for r in rows}
    json.dump(scores, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"{'spk':<7}{'label':<14}{'PESQ':>6}{'STOI':>7}{'SISDR':>7}")
    for r in rows:
        print(f"{r['name']:<7}{r['label']:<14}{r['pesq']:>6.2f}{r['stoi']:>7.3f}{r['si_sdr']:>7.1f}")
    ps = np.array([r["pesq"] for r in rows])
    print(f"\nPESQ: min={ps.min():.2f} p25={np.percentile(ps,25):.2f} "
          f"median={np.median(ps):.2f} max={ps.max():.2f}  n={len(ps)}")
    print(f"保存: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
