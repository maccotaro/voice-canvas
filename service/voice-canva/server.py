"""声のCanva 推論サービス server (FastAPI)。

HTTP API。
意味軸スライダー → Seed-VC 生成。GPU(CUDA)前提だが CPU でも動作。

起動（コンテナ内）:
  uvicorn server:app --host 0.0.0.0 --port 8770
ローカル(voice-canva リポ, cwd=external/seed-vc 相当の Seed-VC が PYTHONPATH に必要):
  VOICE_CANVA_PROJ=<repo> HF_HUB_OFFLINE=1 PYTHONPATH=<seed-vc>:<repo> \
    uvicorn service.voice-canva.server:app --port 8770
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import anchor_admin as admin
import canva_service as svc
import material_tools as tools

app = FastAPI(title="Voice Canva Inference", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_READY = {"ok": False, "info": None}


class GenerateReq(BaseModel):
    sliders: dict[str, float]
    carrier_b64: str | None = None
    speed: float | None = None            # 話すスピード(x)
    pitch_variation: float | None = None  # ピッチの揺らぎ(0..100)
    breathiness: float | None = None      # 息遣いの強さ(0..100)
    faithful: bool = False                # 学習素材用の忠実モード(AUTO_F0 off/steps多め/DSP off/CFG低)
    cfg_rate: float | None = None         # inference_cfg_rate 明示指定(実験用)。無指定はモード既定
    anchors: list[str] | None = None      # 使うアンカーを絞る（名前の一覧）。無指定は全員から選ぶ


class AudioReq(BaseModel):
    audio_b64: str
    name: str | None = None


class UploadReq(BaseModel):
    audio_b64: str
    filename: str | None = None


def _err(e: Exception) -> HTTPException:
    """利用者向けのエラーは 4xx で理由を返し、それ以外は 500。"""
    if isinstance(e, svc.NotReady):
        return HTTPException(409, str(e))
    if isinstance(e, (admin.AnchorError, tools.ToolError)):
        return HTTPException(400, str(e))
    return HTTPException(500, str(e))


@app.on_event("startup")
def _startup():
    _READY["info"] = svc.init()
    _READY["ok"] = True
    print(f"[voice-canva] ready: {_READY['info']}", flush=True)


@app.get("/health")
def health():
    return {"status": "ok" if _READY["ok"] else "loading", "service": "voice-canva", **(_READY["info"] or {})}


@app.get("/axes")
def axes():
    return svc.list_axes()


@app.get("/anchors")
def anchors():
    return svc.list_anchors()


# ---------------- アンカー管理（一覧・取り込み・退避・復元） ----------------
@app.get("/anchors/admin")
def anchors_admin():
    return admin.overview()


@app.get("/anchors/uploads")
def anchor_uploads():
    return admin.jobs()


@app.post("/anchors/uploads")
def anchor_upload(req: UploadReq):
    try:
        return admin.submit(req.audio_b64, req.filename)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.post("/anchors/uploads/clear")
def anchor_uploads_clear():
    return admin.clear_finished()


@app.post("/anchors/{name}/exclude")
def anchor_exclude(name: str):
    try:
        return admin.exclude(name)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.post("/anchors/{name}/restore")
def anchor_restore(name: str):
    try:
        return admin.restore(name)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.post("/anchors/{name}/delete")
def anchors_delete(name: str):
    """自分で足したアンカーを完全に削除する（同梱のアンカーは不可）。"""
    try:
        return admin.delete(name)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/anchor_audio/{name}")
def anchor_audio(name: str):
    return FileResponse(svc.anchor_audio_path(name), media_type="audio/wav")


class ToolAudioReq(BaseModel):
    audio_b64: str
    filename: str | None = None


@app.post("/tools/separate")
def tools_separate(req: ToolAudioReq):
    """素材ツール: BGM・雑音を除いて声だけを残す（裏で 1 本ずつ処理。進み具合は GET で取る）。"""
    try:
        return tools.submit(req.audio_b64, req.filename)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/tools/separate/{jid}")
def tools_separate_status(jid: str):
    try:
        return tools.status(jid)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/tools/separate/{jid}/audio")
def tools_separate_audio(jid: str):
    try:
        return FileResponse(tools.result_path(jid), media_type="audio/wav")
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.get("/sample_source")
def sample_source():
    """同梱の変換元音声（Common Voice の1クリップ・CC0）。手元に音声が無くても試せるように画面へ渡す。"""
    path = svc._carrier()
    if not os.path.exists(path):
        raise HTTPException(404, "同梱の変換元音声がありません")
    return FileResponse(path, media_type="audio/wav")


@app.post("/analyze")
def analyze(req: AudioReq):
    try:
        return svc.analyze(req.audio_b64)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


class PostProcessReq(BaseModel):
    speed: float | None = None
    pitch_variation: float | None = None
    breathiness: float | None = None
    take_id: int | None = None


@app.post("/generate")
def generate(req: GenerateReq):
    try:
        return svc.generate(req.sliders, req.carrier_b64,
                            speed=req.speed, pitch_variation=req.pitch_variation,
                            breathiness=req.breathiness, faithful=req.faithful,
                            cfg_rate=req.cfg_rate, anchors=req.anchors)
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.post("/postprocess")
def postprocess(req: PostProcessReq):
    """テイク(省略時は直近)に後処理(話速/揺らぎ/息遣い)のみ再適用（モデル再実行なし・即時）。"""
    try:
        return svc.postprocess(speed=req.speed, pitch_variation=req.pitch_variation,
                               breathiness=req.breathiness, take_id=req.take_id)
    except Exception as e:  # noqa: BLE001
        raise _err(e)
