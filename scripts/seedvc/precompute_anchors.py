"""全アンカーの campplus 話者埋め込みを事前計算して保存。

声のCanva MVP のバックエンドが「意味軸→アンカー重み→ブレンド埋め込み」を組むための土台。
data/tgt_spkN_long.wav からは campplus 埋め込みを、属性(F0/HNR等)は features/spkN.npz から
別途取得する。出力: data/anchor_embeddings.npz （name -> 192d vector）

cwd=external/seed-vc 前提。
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import librosa
import numpy as np
import torch
import torchaudio

from inference import load_models

_PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _PROJ)
from voice_canva.seedvc_device import configure_seedvc_device  # noqa: E402

device = configure_seedvc_device()   # load_models より前に呼ぶ（Mac で MPS を避ける）
OUT = os.path.join(_PROJ, "data/anchor_embeddings.npz")


def _args():
    a = argparse.Namespace()
    a.f0_condition = False; a.auto_f0_adjust = False; a.semi_tone_shift = 0
    a.checkpoint = None; a.config = None; a.fp16 = False
    return a


def main():
    model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = load_models(_args())
    sr = mel_fn_args["sampling_rate"]
    refs = sorted(glob.glob(os.path.join(_PROJ, "data/tgt_spk*_long.wav")),
                  key=lambda p: int("".join(filter(str.isdigit, os.path.basename(p)))))
    names, vecs = [], []
    with torch.inference_mode():
        for p in refs:
            name = os.path.basename(p).replace("tgt_", "").replace("_long.wav", "")
            y = librosa.load(p, sr=sr)[0]
            yt = torch.tensor(y[: int(sr * 25)]).unsqueeze(0).float().to(device)
            w16 = torchaudio.functional.resample(yt, sr, 16000)
            feat = torchaudio.compliance.kaldi.fbank(w16, num_mel_bins=80, dither=0, sample_frequency=16000)
            feat = feat - feat.mean(dim=0, keepdim=True)
            emb = campplus_model(feat.unsqueeze(0)).squeeze().detach().cpu().numpy()
            names.append(name); vecs.append(emb.astype(np.float32))
            print(f"{name}: emb dim={emb.shape}", flush=True)
    np.savez(OUT, names=np.array(names), embeddings=np.stack(vecs))
    print(f"saved {len(names)} anchors -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
