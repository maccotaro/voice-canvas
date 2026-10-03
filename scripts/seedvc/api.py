"""声のCanva バックエンドAPI (FastAPI): 意味軸スライダー → Seed-VC 生成をHTTP化。

Next.js フロント(web/)が BFF 経由で叩く。app_canva.py と同じコア(design + Seed-VC)を
HTTPエンドポイントとして公開する。

起動(cwd=external/seed-vc):
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=. \
    ../../.venv-seedvc/bin/uvicorn api:app --host 127.0.0.1 --port 8009

エンドポイント:
  GET  /api/axes              軸定義
  GET  /api/anchors           アンカー一覧(名前/スライダー値)
  GET  /api/anchor_audio/{n}  アンカー試聴wav
  POST /api/generate          {sliders, carrier_b64?} → {wav_b64, info, top}
  POST /api/analyze           {audio_b64} → {sliders}
  POST /api/add_anchor        {audio_b64, name?} → {name, sliders, anchors}
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile

import librosa
import numpy as np
import soundfile as sf
import torch
import torchaudio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

_PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _PROJ)
from voice_canva import design  # noqa: E402
from inference import load_models  # noqa: E402
from voice_canva.seedvc_device import configure_seedvc_device  # noqa: E402

device = configure_seedvc_device()   # load_models より前に呼ぶ（Mac で MPS を避ける）

CARRIER = os.path.join(_PROJ, "data/spk2.wav")
OUTDIR = os.path.join(_PROJ, "output/canva")
USER_DIR = os.path.join(_PROJ, "data/user_anchors")
STEPS, CFG, PROMPT_S = 30, 0.7, 4.0
S = {}

app = FastAPI(title="声のCanva API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _args():
    import argparse
    a = argparse.Namespace()
    a.f0_condition = a.auto_f0_adjust = False
    a.semi_tone_shift = 0
    a.checkpoint = a.config = None
    a.fp16 = False
    return a


@app.on_event("startup")
def _startup():
    os.makedirs(OUTDIR, exist_ok=True)
    model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = load_models(_args())
    sr = mel_fn_args["sampling_rate"]
    bank = design.load_bank()
    anchor_audio = {n: os.path.join(_PROJ, f"data/{n}.wav") for n in bank.names}
    for name, emb, attr, wav in _load_user_anchors():
        bank = design.add_anchor(bank, name, emb, attr)
        anchor_audio[name] = wav
    src = librosa.load(CARRIER, sr=sr)[0]
    src_t = torch.tensor(src).unsqueeze(0).float().to(device)
    with torch.inference_mode():
        s_alt = semantic_fn(torchaudio.functional.resample(src_t, sr, 16000))
        mel = mel_fn(src_t.float())
        cond, *_ = model.length_regulator(s_alt, ylens=torch.LongTensor([mel.size(2)]).to(device),
                                          n_quantizers=3, f0=None)
    S.update(model=model, semantic_fn=semantic_fn, vocoder_fn=vocoder_fn, campplus_model=campplus_model,
             mel_fn=mel_fn, sr=sr, bank=bank, cond=cond, default_cond=cond, anchor_audio=anchor_audio)
    print(f"[api] ready axes={bank.active_axes} anchors={len(bank.names)}", flush=True)


# ---- 永続化（app_canva と同形式） ----
def _load_user_anchors():
    import glob
    import json
    out = []
    for npz in sorted(glob.glob(os.path.join(USER_DIR, "*.npz"))):
        name = os.path.basename(npz)[:-4]
        d = np.load(npz)
        jf = os.path.join(USER_DIR, f"{name}.json")
        sc = json.load(open(jf, encoding="utf-8")) if os.path.exists(jf) else {}
        attr = dict(formants=d["formants"].astype(float),
                    **{k: float(sc.get(k, 0.0)) for k in ("f0_mean", "hnr", "spectral_tilt", "shimmer", "jitter")})
        out.append((name, d["embedding"].astype(float), attr, os.path.join(USER_DIR, f"{name}.wav")))
    return out


def _save_user_anchor(name, wav_src, emb, attr):
    import json
    import shutil
    os.makedirs(USER_DIR, exist_ok=True)
    dst = os.path.join(USER_DIR, f"{name}.wav")
    try:
        shutil.copyfile(wav_src, dst)
    except Exception:
        dst = wav_src
    np.savez(os.path.join(USER_DIR, f"{name}.npz"),
             embedding=np.asarray(emb, np.float32), formants=np.asarray(attr["formants"], np.float32))
    with open(os.path.join(USER_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump({k: float(attr[k]) for k in ("f0_mean", "hnr", "spectral_tilt", "shimmer", "jitter")}, f)
    return dst


def _b64_to_wav(b64: str) -> str:
    raw = base64.b64decode(b64.split(",")[-1])
    fd, path = tempfile.mkstemp(suffix=".wav", dir=OUTDIR)
    os.close(fd)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _anchor_ref_path(n):
    long = os.path.join(_PROJ, f"data/tgt_{n}_long.wav")
    if os.path.exists(long):
        return long
    return S["anchor_audio"].get(n) or os.path.join(_PROJ, f"data/{n}.wav")


def _cond_from_audio(path):
    src = librosa.load(path, sr=S["sr"])[0]
    src_t = torch.tensor(src).unsqueeze(0).float().to(device)
    with torch.inference_mode():
        s_alt = S["semantic_fn"](torchaudio.functional.resample(src_t, S["sr"], 16000))
        mel = S["mel_fn"](src_t.float())
        cond, *_ = S["model"].length_regulator(s_alt, ylens=torch.LongTensor([mel.size(2)]).to(device),
                                               n_quantizers=3, f0=None)
    return cond


def _attr_from_audio(path):
    from voice_canva import analysis
    f = analysis.analyze_wav(path)
    return dict(f0_mean=float(f.f0_mean), hnr=float(f.hnr), spectral_tilt=float(f.spectral_tilt),
                shimmer=float(f.shimmer), jitter=float(f.jitter), formants=np.asarray(f.formants, float))


def _embed_audio(path):
    y = librosa.load(path, sr=S["sr"])[0]
    yt = torch.tensor(y[: int(S["sr"] * 25)]).unsqueeze(0).float().to(device)
    w16 = torchaudio.functional.resample(yt, S["sr"], 16000)
    feat = torchaudio.compliance.kaldi.fbank(w16, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    return S["campplus_model"](feat.unsqueeze(0)).squeeze().detach().cpu().numpy()


# ---- スキーマ ----
class GenReq(BaseModel):
    sliders: dict[str, float]
    carrier_b64: str | None = None


class AudioReq(BaseModel):
    audio_b64: str
    name: str | None = None


# ---- エンドポイント ----
@app.get("/api/axes")
def axes():
    return [{"key": a.key, "label": a.label, "low": a.low, "high": a.high, "status": a.status}
            for a in design.AXES]


def _anchor_payload():
    av = design.anchor_slider_values(S["bank"])
    return [{"name": n, "sliders": dict(zip(design.AXIS_KEYS, av[n]))} for n in S["bank"].names]


@app.get("/api/anchors")
def anchors():
    return _anchor_payload()


@app.get("/api/anchor_audio/{name}")
def anchor_audio(name: str):
    p = S["anchor_audio"].get(name) or os.path.join(_PROJ, f"data/{name}.wav")
    return FileResponse(p, media_type="audio/wav")


@app.post("/api/analyze")
def analyze(req: AudioReq):
    path = _b64_to_wav(req.audio_b64)
    sv = design.slider_values_from_attrs(_attr_from_audio(path), S["bank"])
    return {"sliders": dict(zip(design.AXIS_KEYS, sv))}


@app.post("/api/add_anchor")
def add_anchor(req: AudioReq):
    path = _b64_to_wav(req.audio_b64)
    attr = _attr_from_audio(path)
    with torch.inference_mode():
        emb = _embed_audio(path)
    nm = (req.name or "").strip() or f"my{sum(1 for n in S['bank'].names if n.startswith('my')) + 1}"
    S["bank"] = design.add_anchor(S["bank"], nm, emb, attr)
    S["anchor_audio"][nm] = _save_user_anchor(nm, path, emb, attr)
    sv = design.anchor_slider_values(S["bank"])[nm]
    return {"name": nm, "sliders": dict(zip(design.AXIS_KEYS, sv)), "anchors": _anchor_payload()}


@app.post("/api/generate")
def generate(req: GenReq):
    sv = {k: float(v) / 100.0 for k, v in req.sliders.items()}
    cond = _cond_from_audio(_b64_to_wav(req.carrier_b64)) if req.carrier_b64 else S["default_cond"]
    emb, top, w = design.design_embedding(sv, S["bank"])
    sr = S["sr"]
    with torch.inference_mode():
        style = torch.tensor(emb, dtype=torch.float32, device=device).reshape(1, -1)
        segs = []
        for n in top:
            p = _anchor_ref_path(n)
            if p and os.path.exists(p):
                y = librosa.load(p, sr=sr)[0]
                segs.append((y / (np.max(np.abs(y)) + 1e-9) * 0.9)[: int(PROMPT_S * sr)])
        cref = np.concatenate(segs) if segs else np.zeros(int(PROMPT_S * sr), np.float32)
        cref_t = torch.tensor(cref).unsqueeze(0).float().to(device)
        w16 = torchaudio.functional.resample(cref_t, sr, 16000)
        s_ori = S["semantic_fn"](w16)
        mel2 = S["mel_fn"](cref_t.float())
        pc, *_ = S["model"].length_regulator(s_ori, ylens=torch.LongTensor([mel2.size(2)]).to(device),
                                             n_quantizers=3, f0=None)
        cat = torch.cat([pc, cond], dim=1)
        with torch.autocast(device_type=device.type, dtype=torch.float32):
            vt = S["model"].cfm.inference(cat, torch.LongTensor([cat.size(1)]).to(device),
                                          mel2, style, None, STEPS, inference_cfg_rate=CFG)
            vt = vt[:, :, mel2.size(-1):]
        wav = S["vocoder_fn"](vt.float()).squeeze().detach().cpu().float().numpy().reshape(-1)
    pk = float(np.max(np.abs(wav)))
    if pk > 0.97:
        wav = wav * (0.97 / pk)
    buf = io.BytesIO()
    sf.write(buf, wav.astype(np.float32), sr, format="WAV")
    b64 = "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode()
    info = [{"name": n, "weight": float(wi)} for n, wi in
            sorted(zip(S["bank"].names, w), key=lambda x: -x[1])[:3]]
    return {"wav_b64": b64, "sr": sr, "top": info}
