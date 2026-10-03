"""素材ツールのうちサーバーで動かすもの: BGM・雑音を除いて声だけを残す（Demucs htdemucs）。server.py から呼ぶ。

ほかのツール（音声抽出・カット・ピッチ・結合・録音）はブラウザの中で処理する。
Demucs は CPU でも音声の長さとほぼ同じ時間で終わる（30 秒の音声に約 36 秒、8 コア）。
1 本ずつキューで処理し、画面は進み具合を取りに来る。モデル（約 80MB）は初回だけ取得する。

Demucs: https://github.com/facebookresearch/demucs （MIT License）。重みは同梱せず、初回に取得する。
"""
from __future__ import annotations

import base64
import os
import queue
import threading
import time
import uuid

import librosa
import numpy as np
import soundfile as sf
import torch

import canva_service as svc
from voice_canva import anchor_select as sel

MAX_SEC = 180.0          # 先頭 3 分まで（ブラウザ側の素材の上限と同じ）
KEEP_JOBS = 20           # 結果ファイルはこの本数だけ残す
MODEL_NAME = os.environ.get("VOICE_CANVA_SEPARATE_MODEL", "htdemucs")
OUT_DIR = os.path.join(svc.PROJ, "output", "tools")

_LOCK = threading.Lock()
_QUEUE: "queue.Queue[str]" = queue.Queue()
_JOBS: dict[str, dict] = {}
_S: dict = {"rate": 1.2}  # 音声 1 秒あたりの処理秒数（見込み）。実測で更新する


class ToolError(ValueError):
    """利用者に理由をそのまま見せてよいエラー。"""


def _model():
    if "model" not in _S:
        from demucs.pretrained import get_model
        m = get_model(MODEL_NAME)
        m.eval()
        _S["model"] = m
    return _S["model"]


def _device():
    # Demucs は MPS で動かないことがあるので、CUDA が無ければ CPU
    return "cuda" if torch.cuda.is_available() and os.environ.get("VOICE_CANVA_DEVICE", "") != "cpu" else "cpu"


def submit(audio_b64: str, filename: str | None) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    jid = uuid.uuid4().hex[:12]
    src = os.path.join(OUT_DIR, f"{jid}_in.wav")
    with open(src, "wb") as f:
        f.write(base64.b64decode(audio_b64.split(",")[-1]))
    try:
        info = sf.info(src)
    except Exception as e:  # noqa: BLE001
        os.remove(src)
        raise ToolError("音声ファイルとして読めませんでした（WAVを送ってください）") from e
    sec = min(float(info.duration), MAX_SEC)
    job = {"id": jid, "filename": os.path.basename(filename or "audio.wav")[:120], "status": "queued",
           "step": "順番待ち", "sec": round(sec, 1), "created": time.time(), "started": None,
           "estimate": round(sec * _S["rate"], 0), "quality_before": None, "quality_after": None}
    _JOBS[jid] = job
    _QUEUE.put(jid)
    _ensure_worker()
    _prune()
    return status(jid)


def status(jid: str) -> dict:
    job = _JOBS.get(jid)
    if job is None:
        raise ToolError("この処理は見つかりません（サービスを再起動すると消えます）")
    out = {k: v for k, v in job.items() if k != "created"}
    if job["status"] == "processing" and job["started"]:
        out["elapsed"] = round(time.time() - job["started"], 0)
    return out


def result_path(jid: str) -> str:
    job = _JOBS.get(jid)
    if job is None or job["status"] != "done":
        raise ToolError("まだできていません")
    return os.path.join(OUT_DIR, f"{jid}_voice.wav")


def _ensure_worker():
    if _S.get("worker") and _S["worker"].is_alive():
        return
    t = threading.Thread(target=_work, name="material-tools", daemon=True)
    _S["worker"] = t
    t.start()


def _work():
    while True:
        jid = _QUEUE.get()
        job = _JOBS.get(jid)
        if job is None:
            continue
        job.update(status="processing", step="読み込み中", started=time.time())
        try:
            with _LOCK:
                _process(jid, job)
            job.update(status="done", step="")
        except ToolError as e:
            job.update(status="error", step="", reason=str(e))
        except Exception as e:  # noqa: BLE001
            job.update(status="error", step="", reason=f"処理中にエラーが起きました: {e}")
        finally:
            src = os.path.join(OUT_DIR, f"{jid}_in.wav")
            if os.path.exists(src):
                os.remove(src)


def _quality(y: np.ndarray, sr: int) -> float | None:
    """アンカー登録と同じ録音品質（SQUIM の PESQ 推定）を、真ん中の 12 秒で測る。"""
    try:
        import anchor_admin
        squim = anchor_admin._squim()
    except Exception:  # noqa: BLE001  品質が測れなくても声の分離は続ける
        return None
    y16 = librosa.resample(y.astype(np.float32), orig_sr=sr, target_sr=sel.SR16)
    # sel.pesq は「center_s - 4 秒」から 12 秒を測るので、真ん中 12 秒の開始 + 4 を渡す
    start = max(0.0, len(y16) / sel.SR16 / 2 - 6.0)
    return round(sel.pesq(squim, y16, start + 4.0), 2)


def _process(jid: str, job: dict) -> None:
    y, sr = sf.read(os.path.join(OUT_DIR, f"{jid}_in.wav"), dtype="float32", always_2d=True)
    y = y[: int(MAX_SEC * sr)]
    mono = y.mean(axis=1)
    if len(mono) < sr:
        raise ToolError("音声が短すぎます（1秒未満）")
    job["quality_before"] = _quality(mono, sr)

    job["step"] = "部品を準備しています（初回は約80MBを取得）" if "model" not in _S else "準備しています"
    model = _model()
    msr = model.samplerate
    x = librosa.resample(y.T, orig_sr=sr, target_sr=msr) if sr != msr else y.T
    if x.shape[0] == 1:
        x = np.repeat(x, 2, axis=0)
    x = torch.tensor(x[:2], dtype=torch.float32)
    # Demucs は入力の平均・分散で正規化して使う（demucs.separate と同じ扱い）
    ref = x.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    job["step"] = "声とそれ以外を分けています"
    t0 = time.time()
    with torch.inference_mode():
        from demucs.apply import apply_model
        out = apply_model(model, ((x - mean) / std)[None], shifts=1, split=True, overlap=0.25,
                          progress=False, device=_device())[0]
    took = time.time() - t0
    _S["rate"] = max(0.2, took / max(1.0, x.shape[-1] / msr))   # 次の見込みに使う
    voice = (out[model.sources.index("vocals")] * std + mean).mean(0).cpu().numpy()
    peak = float(np.max(np.abs(voice))) or 1.0
    voice = (voice / peak * 0.9).astype(np.float32)
    sf.write(os.path.join(OUT_DIR, f"{jid}_voice.wav"), voice, msr, subtype="PCM_16")
    job["step"] = "録音品質を測っています"
    job["quality_after"] = _quality(voice, msr)


def _prune():
    done = sorted((j for j in _JOBS.values() if j["status"] in ("done", "error")), key=lambda j: j["created"])
    for j in done[:-KEEP_JOBS] if len(done) > KEEP_JOBS else []:
        p = os.path.join(OUT_DIR, f"{j['id']}_voice.wav")
        if os.path.exists(p):
            os.remove(p)
        _JOBS.pop(j["id"], None)
