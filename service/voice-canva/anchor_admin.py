"""アンカーの管理（素材の取り込み・一覧・退避・復元・削除）。server.py から呼ぶ。

取り込みは CLI（scripts/seedvc/select_anchors.py）と同じ選定ロジック（voice_canva.anchor_select）を使う。
1 素材 = 1 話者の録音。CPU だと 1 本あたり数分かかるので、キューに積んで 1 本ずつ裏で処理し、
画面は進み具合を取りに来る。

ファイル配置（CLI と同じ形式）:
  data/spkN.wav, data/tgt_spkN_long.wav, features/spkN.npz, data/anchor_embeddings.npz
  data/anchor_sources.json（spkN → 素材ファイル名）, data/anchor_meta.json（品質などの記録）
  退避: data/_excluded/, features/_excluded/, data/user_anchors/_excluded/
  削除: 自分で足したアンカーだけ。同梱パック（anchors/default）のアンカーは外せるが削除はできない
"""
from __future__ import annotations

import base64
import glob
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid

import librosa
import numpy as np
import soundfile as sf
import torch
import torchaudio

import canva_service as svc
from voice_canva import anchor_select as sel
from voice_canva import default_anchors, design

DATA = os.path.join(svc.PROJ, "data")
FEAT = os.path.join(svc.PROJ, "features")
EMB = os.path.join(DATA, "anchor_embeddings.npz")
SOURCES = os.path.join(DATA, "anchor_sources.json")
META = os.path.join(DATA, "anchor_meta.json")
UPLOADS = os.path.join(DATA, "_uploads")
EX_DATA = os.path.join(DATA, "_excluded")
EX_FEAT = os.path.join(FEAT, "_excluded")
EX_USER = os.path.join(svc.USER_DIR, "_excluded")

MAX_UPLOAD_SEC = 300.0
_NAME_RE = re.compile(r"^[\w\-ぁ-んァ-ヶ一-龥ー]{1,40}$")

_LOCK = threading.RLock()          # バンクとファイルの更新を直列化
_QUEUE: "queue.Queue[str]" = queue.Queue()
_JOBS: dict[str, dict] = {}        # 取り込みの状態（プロセス内のみ。再起動で消える）
_WORKER: dict = {}
_SQUIM: dict = {}


class AnchorError(ValueError):
    """利用者に理由をそのまま見せてよいエラー。"""


# ---------------- 小物 ----------------
def _read_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_json(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _write_emb(names: list[str], vecs: np.ndarray) -> None:
    tmp = EMB + ".tmp.npz"
    # 最後の1人を外したときは 0 件で書く（reshape(0, -1) は形が決まらず失敗するので次元を明示する）
    emb = np.asarray(vecs, np.float32).reshape(len(names), -1) if names else np.zeros((0, 192), np.float32)
    np.savez(tmp, names=np.array(names, dtype=str), embeddings=emb)
    os.replace(tmp, EMB)


def _read_emb() -> tuple[list[str], np.ndarray]:
    if not os.path.exists(EMB):
        return [], np.zeros((0, 192), np.float32)
    d = np.load(EMB, allow_pickle=True)
    return [str(x) for x in d["names"]], d["embeddings"].astype(np.float32)


def _check_name(name: str) -> str:
    if not _NAME_RE.match(name or ""):
        raise AnchorError("アンカー名が不正です")
    return name


def _next_name() -> str:
    nums = [0]
    for p in glob.glob(os.path.join(DATA, "tgt_spk*_long.wav")) + glob.glob(os.path.join(EX_DATA, "tgt_spk*_long.wav")):
        m = re.search(r"tgt_spk(\d+)_long\.wav$", p)
        if m:
            nums.append(int(m.group(1)))
    return f"spk{max(nums) + 1}"


def _squim():
    if "m" not in _SQUIM:
        from torchaudio.pipelines import SQUIM_OBJECTIVE
        try:
            _SQUIM["m"] = SQUIM_OBJECTIVE.get_model().eval()
        except Exception as e:  # noqa: BLE001
            raise AnchorError(f"録音品質の判定モデルを読み込めませんでした: {e}") from e
    return _SQUIM["m"]


def _embed16(seg16: np.ndarray) -> np.ndarray:
    dev = svc._S["device"]
    yt = torch.tensor(seg16).unsqueeze(0).float().to(dev)
    feat = torchaudio.compliance.kaldi.fbank(yt, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    return svc._S["campplus_model"](feat.unsqueeze(0)).squeeze().detach().cpu().numpy()


def _attr_from_feat(f) -> dict:
    return dict(f0_mean=float(f.f0_mean), hnr=float(f.hnr), spectral_tilt=float(f.spectral_tilt),
                shimmer=float(f.shimmer), jitter=float(f.jitter), formants=np.asarray(f.formants, float))


# ---------------- 取り込み ----------------
def submit(audio_b64: str, filename: str | None) -> dict:
    """素材を 1 本受け付けてキューに積む。処理は裏のスレッドで 1 本ずつ行う。"""
    os.makedirs(UPLOADS, exist_ok=True)
    jid = uuid.uuid4().hex[:12]
    path = os.path.join(UPLOADS, f"{jid}.wav")
    raw = base64.b64decode(audio_b64.split(",")[-1])
    with open(path, "wb") as f:
        f.write(raw)
    try:
        info = sf.info(path)
    except Exception as e:  # noqa: BLE001
        os.remove(path)
        raise AnchorError("音声ファイルとして読めませんでした（WAVを送ってください）") from e
    job = {"id": jid, "filename": os.path.basename(filename or "recording.wav")[:120],
           "status": "queued", "step": "順番待ち", "sec": round(float(info.duration), 1),
           "created": time.time()}
    _JOBS[jid] = job
    _QUEUE.put(jid)
    _ensure_worker()
    return dict(job)


def jobs() -> list[dict]:
    return sorted((dict(j) for j in _JOBS.values()), key=lambda j: j["created"], reverse=True)


def clear_finished() -> list[dict]:
    for jid in [j for j, v in _JOBS.items() if v["status"] in ("accepted", "rejected", "error")]:
        _JOBS.pop(jid, None)
    return jobs()


def _ensure_worker() -> None:
    t = _WORKER.get("t")
    if t is None or not t.is_alive():
        t = threading.Thread(target=_work, name="anchor-worker", daemon=True)
        _WORKER["t"] = t
        t.start()


def _work() -> None:
    while True:
        jid = _QUEUE.get()
        job = _JOBS.get(jid)
        if job is None:
            continue
        job.update(status="processing", step="読み込み中", started=time.time())
        path = os.path.join(UPLOADS, f"{jid}.wav")
        try:
            job.update(_process(path, job))
        except AnchorError as e:
            job.update(status="error", step="", reason=str(e))
        except Exception as e:  # noqa: BLE001
            job.update(status="error", step="", reason=f"処理中にエラーが起きました: {e}")
        finally:
            job["finished"] = time.time()
            if os.path.exists(path):
                os.remove(path)


def _process(path: str, job: dict) -> dict:
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    y = y[: int(MAX_UPLOAD_SEC * sr)]
    if len(y) < sel.LIGHT_MIN_SEC * sr:
        return {"status": "rejected", "step": "",
                "reason": f"素材が短すぎます（{len(y) / sr:.0f}秒）。{sel.LIGHT_MIN_SEC:.0f}秒以上の録音が必要です"}
    y16 = librosa.resample(y, orig_sr=sr, target_sr=sel.SR16)
    squim = _squim()

    def step(msg: str) -> None:
        job["step"] = msg

    # 長いファイル（コーパスなど）は端5秒を避ける。短い録音は端0.5秒だけ避ける
    guard = sel.GUARD_S if len(y) / sr >= 30 else sel.LIGHT_GUARD_S
    with torch.inference_mode():
        best, _passed = sel.select_best(_embed16, y16, sel.HOMO_THRESH, squim=squim,
                                        pesq_thresh=sel.PESQ_THRESH, on_progress=step,
                                        guard_s=guard, unknown_ok=True)
    if best is None:
        return {"status": "rejected", "step": "",
                "reason": "話し声の区間が見つかりませんでした（無音・雑音・音楽が多い可能性があります）"}
    homog = best.get("homog")
    metrics = {"quality": round(float(best.get("pesq", 0.0)), 2),
               "single": None if homog is None else round(float(homog), 2),
               "f0": round(float(best["f0"]), 0), "at": round(float(best["center"]), 1)}
    # 基準に届かないものも採用し、注意として残す（表と処理の状況に出す）
    warnings = []
    if homog is None:
        warnings.append("短いため、1人だけの声かは確かめていません")
    elif homog < sel.HOMO_THRESH:
        warnings.append("ほかの人の声が混ざっているかもしれません")
    if metrics["quality"] < sel.PESQ_THRESH:
        warnings.append(f"録音品質が低めです（{metrics['quality']:.2f}）。雑音や反響で声がざらつくことがあります")

    job["step"] = "アンカーとして保存しています"
    seg4, seg12 = sel.cut_windows(y, sr, best["center"])
    with _LOCK:
        name = _next_name()
        os.makedirs(FEAT, exist_ok=True)
        wav4 = os.path.join(DATA, f"{name}.wav")
        wav12 = os.path.join(DATA, f"tgt_{name}_long.wav")
        sf.write(wav4, seg4, sr, subtype="PCM_16")
        sf.write(wav12, seg12, sr, subtype="PCM_16")
        from voice_canva import analysis
        feat = analysis.analyze_wav(wav4, name=name)
        attr = _attr_from_feat(feat)
        # 保存するのは音響スカラだけ（f0/sp/ap の配列は元の声を再合成できるので残さない）
        design.write_attrs({name: attr})
        with torch.inference_mode():
            emb = svc._embed_audio(wav12)
        names, vecs = _read_emb()
        _write_emb(names + [name], np.vstack([vecs, np.asarray(emb, np.float32).reshape(1, -1)]))
        src = _read_json(SOURCES)
        src[name] = job["filename"]
        _write_json(SOURCES, src)
        meta = _read_json(META)
        meta[name] = {**metrics, "source": job["filename"], "added": time.strftime("%Y-%m-%d %H:%M"),
                      "warnings": warnings}
        _write_json(META, meta)
        svc._S["bank"] = design.add_anchor(svc._S["bank"], name, emb, attr)
        svc._S["anchor_audio"][name] = wav4
    return {"status": "accepted", "step": "", "name": name, "metrics": metrics, "warnings": warnings}


# ---------------- 一覧・退避・復元 ----------------
def overview() -> dict:
    bank = svc._S["bank"]
    sv = design.anchor_slider_values(bank)
    meta, src = _read_json(META), _read_json(SOURCES)
    base = set(_read_emb()[0])
    bundled = default_anchors.bundled_names(svc.PROJ)
    items = []
    for n in bank.names:
        m = meta.get(n, {})
        items.append({"name": n, "kind": "base" if n in base else "user", "bundled": n in bundled,
                      "source": m.get("source") or src.get(n) or "",
                      "quality": m.get("quality"), "single": m.get("single"), "added": m.get("added"),
                      "warnings": m.get("warnings") or [],
                      "f0": round(float(bank.attrs[bank.names.index(n)]["f0_mean"]), 0),
                      "sliders": dict(zip(design.AXIS_KEYS, sv[n]))})
    excluded = []
    for p in sorted(glob.glob(os.path.join(EX_DATA, "tgt_*_long.wav"))):
        n = os.path.basename(p)[4:-9]
        excluded.append({"name": n, "kind": "base", "bundled": n in bundled,
                         "source": meta.get(n, {}).get("source") or src.get(n) or ""})
    for p in sorted(glob.glob(os.path.join(EX_USER, "*.npz"))):
        excluded.append({"name": os.path.basename(p)[:-4], "kind": "user", "bundled": False, "source": ""})
    return {"anchors": items, "excluded": excluded, "min_anchors": design.MIN_ANCHORS,
            "ready": len(bank.names) >= design.MIN_ANCHORS,
            "pending": sum(1 for j in _JOBS.values() if j["status"] in ("queued", "processing"))}


def _move(src: str, dst_dir: str) -> None:
    if os.path.exists(src):
        os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src, os.path.join(dst_dir, os.path.basename(src)))


def exclude(name: str) -> dict:
    """アンカーを外して退避する（ファイルは消さず _excluded へ移す）。"""
    _check_name(name)
    with _LOCK:
        bank = svc._S["bank"]
        if name not in bank.names:
            raise AnchorError(f"アンカー「{name}」はありません")
        names, vecs = _read_emb()
        if name in names:
            keep = [i for i, n in enumerate(names) if n != name]
            _write_emb([names[i] for i in keep], vecs[keep])
            for f in (f"{name}.wav", f"tgt_{name}_long.wav"):
                _move(os.path.join(DATA, f), EX_DATA)
            _move(os.path.join(FEAT, f"{name}.npz"), EX_FEAT)
        else:
            for ext in ("wav", "npz", "json"):
                _move(os.path.join(svc.USER_DIR, f"{name}.{ext}"), EX_USER)
        svc._S["bank"] = design.remove_anchor(bank, name)
        svc._S["anchor_audio"].pop(name, None)
    return overview()


def restore(name: str) -> dict:
    """退避したアンカーを戻す。"""
    _check_name(name)
    with _LOCK:
        if name in svc._S["bank"].names:
            raise AnchorError(f"アンカー「{name}」はすでにあります")
        from voice_canva.analysis import SpeakerFeatures
        ex12 = os.path.join(EX_DATA, f"tgt_{name}_long.wav")
        if os.path.exists(ex12):
            for f in (f"{name}.wav", f"tgt_{name}_long.wav"):
                _move(os.path.join(EX_DATA, f), DATA)
            _move(os.path.join(EX_FEAT, f"{name}.npz"), FEAT)
            with torch.inference_mode():
                emb = svc._embed_audio(os.path.join(DATA, f"tgt_{name}_long.wav"))
            scal = design.read_attrs()
            attr = scal[name] if name in scal else _attr_from_feat(
                SpeakerFeatures.load(os.path.join(FEAT, f"{name}.npz")))
            names, vecs = _read_emb()
            _write_emb(names + [name], np.vstack([vecs, np.asarray(emb, np.float32).reshape(1, -1)]))
            audio = os.path.join(DATA, f"{name}.wav")
        elif os.path.exists(os.path.join(EX_USER, f"{name}.npz")):
            for ext in ("wav", "npz", "json"):
                _move(os.path.join(EX_USER, f"{name}.{ext}"), svc.USER_DIR)
            loaded = {n: (e, a, w) for n, e, a, w in svc._load_user_anchors()}
            emb, attr, audio = loaded[name]
        else:
            raise AnchorError(f"外したアンカー「{name}」は見つかりません")
        svc._S["bank"] = design.add_anchor(svc._S["bank"], name, emb, attr)
        svc._S["anchor_audio"][name] = audio
    return overview()


def delete(name: str) -> dict:
    """自分で足したアンカーを完全に削除する（使用中・外したもののどちらでも）。同梱のアンカーは削除できない。"""
    _check_name(name)
    if name in default_anchors.bundled_names(svc.PROJ):
        raise AnchorError("同梱のアンカーは削除できません（外すことはできます）")
    with _LOCK:
        found = False
        bank = svc._S["bank"]
        if name in bank.names:
            svc._S["bank"] = design.remove_anchor(bank, name)
            found = True
        names, vecs = _read_emb()
        if name in names:
            keep = [i for i, n in enumerate(names) if n != name]
            _write_emb([names[i] for i in keep], vecs[keep])
            found = True
        files = [os.path.join(d, f) for d in (DATA, EX_DATA) for f in (f"{name}.wav", f"tgt_{name}_long.wav")]
        files += [os.path.join(d, f"{name}.npz") for d in (FEAT, EX_FEAT)]
        files += [os.path.join(d, f"{name}.{ext}") for d in (svc.USER_DIR, EX_USER) for ext in ("wav", "npz", "json")]
        for path in files:
            if os.path.exists(path):
                os.remove(path)
                found = True
        if not found:
            raise AnchorError(f"アンカー「{name}」はありません")
        for path in (SOURCES, META):
            rec = _read_json(path)
            if rec.pop(name, None) is not None:
                _write_json(path, rec)
        design.remove_attrs([name])
        svc._S["anchor_audio"].pop(name, None)
    return overview()
