"""Seed-VC 中間声（埋め込み線形lerp版）: 連結秒数の非線形/飽和を回避。

連結秒数だと spk15 側で飽和して 75≈100 になった。本版は:
  - style2 = (1-w)*campplus(A) + w*campplus(B)   ← 埋め込み空間で線形に制御
  - mel prompt / 意味prompt = A,B を連結した固定参照（両声テクスチャでコヒーレント生成・掠れ無し）
campplus 空間は話者同一性に対し概ね線形なので、w に対し均等な中間声が得られることを狙う。

cwd=external/seed-vc 前提。出力: output/vc/emblerp/blend_*.wav
"""
from __future__ import annotations

import argparse
import os
import sys

import librosa
import numpy as np
import soundfile as sf
import torch
import torchaudio

from inference import load_models

_PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _PROJ)
from voice_canva.seedvc_device import configure_seedvc_device  # noqa: E402

device = configure_seedvc_device()   # load_models より前に呼ぶ（Mac で MPS を避ける）
SOURCE = os.path.join(_PROJ, "data/spk2.wav")
REF_A = os.path.join(_PROJ, "data/tgt_spk13_long.wav")
REF_B = os.path.join(_PROJ, "data/tgt_spk15_long.wav")
OUTDIR = os.path.join(_PROJ, "output/vc/emblerp")
STEPS = 30
CFG = 0.7
PROMPT_S = 4.0          # 連結プロンプトに使う各話者の秒数
WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _log(m): print(f"[emb] {m}", flush=True)


def _args():
    a = argparse.Namespace()
    a.f0_condition = False; a.auto_f0_adjust = False; a.semi_tone_shift = 0
    a.checkpoint = None; a.config = None; a.fp16 = False
    return a


def _load_mono(path, sr):
    y = librosa.load(path, sr=sr)[0]
    return y / (np.max(np.abs(y)) + 1e-9) * 0.9


def _campplus(wave_t, sr, campplus_model):
    w16 = torchaudio.functional.resample(wave_t, sr, 16000)
    feat = torchaudio.compliance.kaldi.fbank(w16, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    return campplus_model(feat.unsqueeze(0))


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    _log("load_models 開始")
    model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = load_models(_args())
    sr = mel_fn_args["sampling_rate"]
    _log(f"load_models 完了 sr={sr}")

    with torch.inference_mode():
        src = librosa.load(SOURCE, sr=sr)[0]
        src_t = torch.tensor(src).unsqueeze(0).float().to(device)
        s_alt = semantic_fn(torchaudio.functional.resample(src_t, sr, 16000))
        mel = mel_fn(src_t.float())
        cond, *_ = model.length_regulator(s_alt, ylens=torch.LongTensor([mel.size(2)]).to(device), n_quantizers=3, f0=None)

        a = _load_mono(REF_A, sr); b = _load_mono(REF_B, sr)
        a_t = torch.tensor(a[: int(PROMPT_S * sr)]).unsqueeze(0).float().to(device)
        b_t = torch.tensor(b[: int(PROMPT_S * sr)]).unsqueeze(0).float().to(device)
        camp_A = _campplus(a_t, sr, campplus_model)
        camp_B = _campplus(b_t, sr, campplus_model)

        # 固定の連結プロンプト（両声テクスチャ）
        cref = np.concatenate([a[: int(PROMPT_S * sr)], b[: int(PROMPT_S * sr)]])
        cref_t = torch.tensor(cref).unsqueeze(0).float().to(device)
        s_ori = semantic_fn(torchaudio.functional.resample(cref_t, sr, 16000))
        mel2 = mel_fn(cref_t.float())
        pc, *_ = model.length_regulator(s_ori, ylens=torch.LongTensor([mel2.size(2)]).to(device), n_quantizers=3, f0=None)
        cat = torch.cat([pc, cond], dim=1)
        cat_len = torch.LongTensor([cat.size(1)]).to(device)

        for w in WEIGHTS:
            style = (1.0 - w) * camp_A + w * camp_B          # 埋め込み線形補間
            with torch.autocast(device_type=device.type, dtype=torch.float32):
                vt = model.cfm.inference(cat, cat_len, mel2, style, None, STEPS, inference_cfg_rate=CFG)
                vt = vt[:, :, mel2.size(-1):]
            wav = vocoder_fn(vt.float()).squeeze().detach().cpu().float().numpy().reshape(-1)
            pk = float(np.max(np.abs(wav)))
            if pk > 0.97: wav = wav * (0.97 / pk)
            out = f"{OUTDIR}/blend_{int(w * 100):03d}.wav"
            sf.write(out, wav.astype(np.float32), sr)
            _log(f"w={w}: {out}")
    _log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
