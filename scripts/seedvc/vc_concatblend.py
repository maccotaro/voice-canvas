"""Seed-VC 中間声（連結参照方式・採用）: 2話者の参照を割合可変で連結→1回生成。

中間度 w (0=A, 1=B): 参照 = A を (1-w)*T 秒 + B を w*T 秒 連結したもの。
campplus 話者埋め込みが連結区間の加重平均＝中間アイデンティティになり、Seed-VC が
1 つの整合した声を生成するため、mel 平均のような櫛干渉（掠れ）が出ない。

cwd=external/seed-vc 前提。出力: output/vc/concatblend/blend_*.wav
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
OUTDIR = os.path.join(_PROJ, "output/vc/concatblend")
STEPS = 30
CFG = 0.7
TOTAL_S = 8.0           # 連結参照の総秒数
MIN_S = 1.5             # 話者が含まれる場合の最小秒数（campplus 安定のため）
WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _log(m): print(f"[concat] {m}", flush=True)


def _args():
    a = argparse.Namespace()
    a.f0_condition = False; a.auto_f0_adjust = False; a.semi_tone_shift = 0
    a.checkpoint = None; a.config = None; a.fp16 = False
    return a


def _load_mono(path, sr):
    y = librosa.load(path, sr=sr)[0]
    return y / (np.max(np.abs(y)) + 1e-9) * 0.9


def _concat_ref(a, b, w, sr):
    """A を (1-w)、B を w の割合で連結した参照波形を返す（端点は単一話者）。"""
    if w <= 0.0:
        return a[: int(TOTAL_S * sr)]
    if w >= 1.0:
        return b[: int(TOTAL_S * sr)]
    da = max(MIN_S, (1.0 - w) * TOTAL_S)
    db = max(MIN_S, w * TOTAL_S)
    return np.concatenate([a[: int(da * sr)], b[: int(db * sr)]])


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

        a = _load_mono(REF_A, sr)
        b = _load_mono(REF_B, sr)

        for w in WEIGHTS:
            ref = _concat_ref(a, b, w, sr)
            ref_t = torch.tensor(ref[: int(sr * 25)]).unsqueeze(0).float().to(device)
            w16 = torchaudio.functional.resample(ref_t, sr, 16000)
            s_ori = semantic_fn(w16)
            mel2 = mel_fn(ref_t.float())
            feat = torchaudio.compliance.kaldi.fbank(w16, num_mel_bins=80, dither=0, sample_frequency=16000)
            feat = feat - feat.mean(dim=0, keepdim=True)
            style = campplus_model(feat.unsqueeze(0))

            pc, *_ = model.length_regulator(s_ori, ylens=torch.LongTensor([mel2.size(2)]).to(device), n_quantizers=3, f0=None)
            cat = torch.cat([pc, cond], dim=1)
            with torch.autocast(device_type=device.type, dtype=torch.float32):
                vt = model.cfm.inference(cat, torch.LongTensor([cat.size(1)]).to(device), mel2, style, None, STEPS, inference_cfg_rate=CFG)
                vt = vt[:, :, mel2.size(-1):]
            wav = vocoder_fn(vt.float()).squeeze().detach().cpu().float().numpy().reshape(-1)
            pk = float(np.max(np.abs(wav)))
            if pk > 0.97: wav = wav * (0.97 / pk)
            out = f"{OUTDIR}/blend_{int(w * 100):03d}.wav"
            sf.write(out, wav.astype(np.float32), sr)
            _log(f"w={w} (A:{(1-w):.2f}/B:{w:.2f}): {out}")
    _log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
