"""声のCanva 推論サービス コア（Seed-VC + 意味軸デザイン）。

推論サービスの中核ロジック。
server.py(FastAPI) から呼ぶ。voice_canva.design（意味軸→アンカー重み→ブレンド埋め込み）と
Seed-VC（inference.py）を統合する。モデルは起動時に1度ロードし、以後リクエストで再利用。

依存（コンテナ）:
- Seed-VC リポジトリ（PYTHONPATH に追加、from inference import ...）
- voice_canva パッケージ（design / analysis）
- data/anchor_embeddings.npz, features/*.npz, data/tgt_*_long.wav（アンカー資産）

環境変数:
- VOICE_CANVA_PROJ : voice_canva 資産のルート（design/analysis が参照）
- VOICE_CANVA_CARRIER : 既定キャリア音声
- VOICE_CANVA_DEVICE : "cuda"/"cpu"（既定: 自動）
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

PROJ = os.environ.get("VOICE_CANVA_PROJ", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, PROJ)
from voice_canva import design  # noqa: E402
from voice_canva.seedvc_device import configure_seedvc_device, select_device  # noqa: E402

# 既定の変換元音声（録音しないで試すとき用）。同梱パック展開後は data/carrier.wav がある
_CARRIER_ENV = os.environ.get("VOICE_CANVA_CARRIER")


def _carrier() -> str:
    if _CARRIER_ENV:
        return _CARRIER_ENV
    c = os.path.join(PROJ, "data/carrier.wav")
    return c if os.path.exists(c) else os.path.join(PROJ, "data/spk2.wav")
OUTDIR = os.path.join(PROJ, "output/canva")
USER_DIR = os.path.join(PROJ, "data/user_anchors")
STEPS = int(os.environ.get("VOICE_CANVA_STEPS", "30"))
CFG = 0.7
PROMPT_S = 4.0
# 44.1kHz F0条件付きモデル（本物の広帯域出力）を使うか。既定OFF（従来22.05kHz）。
F0_COND = os.environ.get("VOICE_CANVA_F0", "0") == "1"
# キャリアのF0を目標(プロンプト)の音域中央値へ寄せる（f0モード時）。
AUTO_F0 = os.environ.get("VOICE_CANVA_AUTO_F0", "1") == "1"
# 学習素材用「忠実モード」の拡散ステップ数（realtime の STEPS と別。細部保存のため多め）。
# 忠実モードでは AUTO_F0 を無効化して感情ごとの音域差(平均ピッチ)を保存し、DSP も掛けない。
# SBV2 のスタイル埋め込みで感情方向が潰れる問題(変換音声のneutral collapse)への対策。
FAITHFUL_STEPS = int(os.environ.get("VOICE_CANVA_FAITHFUL_STEPS", "30"))
# 忠実モード時の inference_cfg_rate。CFG が高いほど生成がターゲットスタイルへ引き寄せられ
# ソースの感情表現が均されるため、忠実モードでは低めを既定にする（realtime は CFG=0.7）。
# env 変更＋Pod再起動だけでスイープできる（再ビルド不要）。
FAITHFUL_CFG = float(os.environ.get("VOICE_CANVA_FAITHFUL_CFG", "0.2"))

_S: dict = {}


class NotReady(RuntimeError):
    """アンカー不足・キャリア無しなど、利用者に対応を促すエラー（server.py が 409 で返す）。"""


def _require_anchors():
    n = len(_S["bank"].names)
    if n < design.MIN_ANCHORS:
        raise NotReady(f"アンカーが足りません（{n}/{design.MIN_ANCHORS}）。"
                       "アンカー管理から話者の録音を追加してください")


def init():
    """モデル＋アンカーバンクをロード（起動時1回）。"""
    from inference import load_models  # Seed-VC

    os.makedirs(OUTDIR, exist_ok=True)
    import argparse
    a = argparse.Namespace(f0_condition=F0_COND, auto_f0_adjust=AUTO_F0, semi_tone_shift=0,
                           checkpoint=None, config=None, fp16=False)
    dev = configure_seedvc_device()   # load_models より前に Seed-VC の device をサービスと揃える
    model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = load_models(a)
    _whisper_fp32_on_cpu(semantic_fn, dev)
    sr = mel_fn_args["sampling_rate"]   # f0モードは44100
    from voice_canva import default_anchors
    n_installed = default_anchors.install(PROJ)   # 初回起動なら同梱アンカーを展開
    if n_installed:
        print(f"[voice-canva] 同梱アンカー {n_installed} 人を展開しました", flush=True)
    bank = design.load_bank()
    anchor_audio = {n: os.path.join(PROJ, f"data/{n}.wav") for n in bank.names}
    for name, emb, attr, wav in _load_user_anchors():
        bank = design.add_anchor(bank, name, emb, attr)
        anchor_audio[name] = wav
    _S.update(model=model, semantic_fn=semantic_fn, vocoder_fn=vocoder_fn, campplus_model=campplus_model,
              mel_fn=mel_fn, f0_fn=f0_fn, sr=sr, bank=bank, anchor_audio=anchor_audio, device=dev)
    # 22.05kHz(非f0)のみ default_cond を事前計算（f0モードは prompt 依存のため generate 内で都度計算）
    if not F0_COND and os.path.exists(_carrier()):
        _S["default_cond"] = _cond_from_audio(_carrier())
    return {"axes": bank.active_axes, "anchors": len(bank.names), "device": str(dev),
            "sr": sr, "f0": F0_COND}


def _whisper_fp32_on_cpu(semantic_fn, dev):
    """Seed-VC は whisper を float16 で読む。CPU には半精度の高速演算が無く約50倍遅くなる
    （15秒の音声で 150秒→3秒）ため、CPU のときだけ float32 に戻す。"""
    if dev.type != "cpu":
        return
    for cell in semantic_fn.__closure__ or ():
        m = cell.cell_contents
        if type(m).__name__ == "WhisperModel" and m.dtype == torch.float16:
            m.float()
            print("[voice-canva] CPU のため whisper を float32 で実行します", flush=True)


# ---------------- 永続化（app_canva と同形式） ----------------
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


# ---------------- 音声ユーティリティ ----------------
def b64_to_wav(b64: str) -> str:
    raw = base64.b64decode(b64.split(",")[-1])
    fd, path = tempfile.mkstemp(suffix=".wav", dir=OUTDIR)
    os.close(fd)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _anchor_ref_path(n):
    long = os.path.join(PROJ, f"data/tgt_{n}_long.wav")
    if os.path.exists(long):
        return long
    return _S["anchor_audio"].get(n) or os.path.join(PROJ, f"data/{n}.wav")


def anchor_audio_path(name):
    return _S["anchor_audio"].get(name) or os.path.join(PROJ, f"data/{name}.wav")


def _semantic(w16):
    """意味特徴を抽出。>30s の長尺は 30s 重複チャンクで分割して連結する。

    whisper エンコーダは一度に最大30秒しか扱えず、長尺をそのまま渡すと先頭30秒ぶんの内容
    しか得られない。これを本来の長さに引き伸ばすと「ゆっくり喋る」出力になるため、本家
    inference.py と同様に 30s(5s重複) チャンクで処理して結合する。
    """
    sfn = _S["semantic_fn"]
    if w16.size(-1) <= 16000 * 30:
        return sfn(w16)
    ov = 5  # 秒
    parts, buf, t = [], None, 0
    while t < w16.size(-1):
        chunk = w16[:, t:t + 16000 * 30] if buf is None else \
            torch.cat([buf, w16[:, t:t + 16000 * (30 - ov)]], dim=-1)
        s = sfn(chunk)
        parts.append(s if t == 0 else s[:, 50 * ov:])   # whisper 50token/s、重複ぶんを除去
        buf = chunk[:, -16000 * ov:]
        t += 30 * 16000 if t == 0 else chunk.size(-1) - 16000 * ov
    return torch.cat(parts, dim=1)


def _cond_from_audio(path):
    dev = _S.get("device") or select_device()
    src = librosa.load(path, sr=_S.get("sr", 22050))[0]
    src_t = torch.tensor(src).unsqueeze(0).float().to(dev)
    with torch.inference_mode():
        s_alt = _semantic(torchaudio.functional.resample(src_t, _S["sr"], 16000))
        mel = _S["mel_fn"](src_t.float())
        cond, *_ = _S["model"].length_regulator(s_alt, ylens=torch.LongTensor([mel.size(2)]).to(dev),
                                                n_quantizers=3, f0=None)
    return cond


def _attr_from_audio(path):
    from voice_canva import analysis
    f = analysis.analyze_wav(path)
    return dict(f0_mean=float(f.f0_mean), hnr=float(f.hnr), spectral_tilt=float(f.spectral_tilt),
                shimmer=float(f.shimmer), jitter=float(f.jitter), formants=np.asarray(f.formants, float))


def _embed_audio(path):
    dev = _S["device"]
    y = librosa.load(path, sr=_S["sr"])[0]
    yt = torch.tensor(y[: int(_S["sr"] * 25)]).unsqueeze(0).float().to(dev)
    w16 = torchaudio.functional.resample(yt, _S["sr"], 16000)
    feat = torchaudio.compliance.kaldi.fbank(w16, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    return _S["campplus_model"](feat.unsqueeze(0)).squeeze().detach().cpu().numpy()


# ---------------- 公開API（server.py が呼ぶ） ----------------
def list_axes():
    return [{"key": a.key, "label": a.label, "low": a.low, "high": a.high, "status": a.status}
            for a in design.AXES]


def list_anchors():
    av = design.anchor_slider_values(_S["bank"])
    return [{"name": n, "sliders": dict(zip(design.AXIS_KEYS, av[n]))} for n in _S["bank"].names]


def analyze(audio_b64):
    _require_anchors()
    path = b64_to_wav(audio_b64)
    sv = design.slider_values_from_attrs(_attr_from_audio(path), _S["bank"])
    return {"sliders": dict(zip(design.AXIS_KEYS, sv))}


def _apply_speed(wav, rate, frame=1024, syn_hop=512, tol=512):
    """話すスピード: WSOLA で音高を保ったままテンポ変更（rate>1 で速く）。

    位相ボコーダ(librosa.time_stretch)は音声で位相のにじみ(ロボット的/反響感)が出やすいため、
    波形相似オーバーラップ加算(WSOLA)で位相連続性を保ち自然にテンポだけ変える。
    """
    if not rate or abs(rate - 1.0) < 1e-3:
        return wav
    x = np.ascontiguousarray(wav.astype(np.float32))
    n = len(x)
    if n < frame * 2:
        return wav
    ana_hop = int(round(syn_hop * float(rate)))
    win = np.hanning(frame).astype(np.float32)
    out_len = int(n / rate) + frame + syn_hop
    y = np.zeros(out_len, np.float32)
    norm = np.zeros(out_len, np.float32)
    xp = np.concatenate([np.zeros(tol, np.float32), x,
                         np.zeros(frame + tol + ana_hop + syn_hop + 4, np.float32)])
    off = tol
    prev_ana = 0
    m = 0
    while True:
        syn = m * syn_hop
        if syn + frame >= out_len:
            break
        ideal = m * ana_hop
        if m == 0:
            a = 0
        else:
            nat = xp[off + prev_ana + syn_hop: off + prev_ana + syn_hop + frame]
            best_d, best = 0, -1e18
            for d in range(-tol, tol + 1, 8):     # ±tol を粗探索して位相整合
                cand = xp[off + ideal + d: off + ideal + frame + d]
                sc = float(np.dot(cand, nat)) / (float(np.linalg.norm(cand)) + 1e-6)
                if sc > best:
                    best, best_d = sc, d
            a = ideal + best_d
        seg = xp[off + a: off + a + frame]
        y[syn:syn + frame] += seg * win
        norm[syn:syn + frame] += win
        prev_ana = a
        m += 1
    y = y / np.maximum(norm, 1e-6)
    return y[:max(1, int(n / rate))]


def _apply_pitch_variation(wav, sr, amt):
    """ピッチの揺らぎ: 低速の分数遅延変調で自然な微小ピッチ変動を付与（amt 0..1）。"""
    if not amt or amt <= 0:
        return wav
    n = len(wav)
    t = np.arange(n) / sr
    rate_hz = 4.5
    max_delay = (0.0030 * amt) * sr           # 最大 ~3.0ms（100%で±約65セントのビブラート）
    delay = max_delay * (0.5 - 0.5 * np.cos(2 * np.pi * rate_hz * t))
    idx = np.clip(np.arange(n) - delay, 0, n - 1)
    i0 = np.floor(idx).astype(int)
    frac = (idx - i0).astype(np.float32)
    i1 = np.minimum(i0 + 1, n - 1)
    return wav[i0] * (1 - frac) + wav[i1] * frac


def _apply_breathiness(wav, sr, amt):
    """息遣いの強さ: WORLD で音源の非周期性(AP)を上げて自然な息漏れ声にする（amt 0..1）。

    息漏れ声＝声道はそのままに音源が気息化した状態。ノイズを"足す"のではなく、WORLDで
    F0/スペクトル包絡/非周期性に分解し、非周期性を上げて再合成する（声そのものを息っぽく作り直す）。
    加算式のように別レイヤーの合成感が出にくく、有声(ピッチ)は保たれる。
    """
    if not amt or amt <= 0:
        return wav
    import pyworld as pw
    x = np.ascontiguousarray(wav.astype(np.float64))
    f0, t = pw.harvest(x, sr)
    sp = pw.cheaptrick(x, f0, t, sr)
    # 「その声の囁き」＝非周期性を全帯域1にして再合成（周期成分を消し気息のみに）
    whisper = pw.synthesize(f0, sp, np.ones_like(pw.d4c(x, f0, t, sr)), sr, frame_period=5.0)
    whisper = whisper.astype(np.float32)
    if len(whisper) < len(wav):
        whisper = np.pad(whisper, (0, len(wav) - len(whisper)))
    whisper = whisper[:len(wav)]
    # RMS を原音に合わせる
    rw = float(np.sqrt(np.mean(wav ** 2))) + 1e-9
    rh = float(np.sqrt(np.mean(whisper ** 2))) + 1e-9
    whisper *= rw / rh
    # 原音(有声)と囁きをクロスフェード: amt=1 で完全に囁き声、0.5 で息漏れ声
    out = wav * (1.0 - amt) + whisper * amt
    pk = float(np.max(np.abs(out)))
    if pk > 0.97:
        out = out * (0.97 / pk)
    return out.astype(np.float32)


def _f0_cond_and_prompt(carrier_path, cref, sr, dev, auto_f0=None):
    """f0モード: キャリア内容(cond)とプロンプト(pc)をF0条件付きで作り mel2 を返す。

    本家 inference.py の f0_condition パスを踏襲。キャリアF0を（auto_f0時）プロンプトの
    音域中央値へ寄せてから length_regulator に渡す。style は呼び出し側の設計埋め込みを使う。
    auto_f0=None のときはグローバル AUTO_F0 を用いる（忠実モードは False を渡し再センタリング停止）。
    """
    if auto_f0 is None:
        auto_f0 = AUTO_F0
    f0fn = _S["f0_fn"]
    cy = librosa.load(carrier_path, sr=sr)[0]
    cy_t = torch.tensor(cy).unsqueeze(0).float().to(dev)
    c16 = torchaudio.functional.resample(cy_t, sr, 16000)
    S_alt = _semantic(c16)
    tgt_len = torch.LongTensor([_S["mel_fn"](cy_t.float()).size(2)]).to(dev)

    cref_t = torch.tensor(cref).unsqueeze(0).float().to(dev)
    p16 = torchaudio.functional.resample(cref_t, sr, 16000)
    S_ori = _semantic(p16)
    mel2 = _S["mel_fn"](cref_t.float())
    tgt2 = torch.LongTensor([mel2.size(2)]).to(dev)

    F0_alt = torch.from_numpy(f0fn(c16[0], thred=0.03)).to(dev)[None].float()
    F0_ori = torch.from_numpy(f0fn(p16[0], thred=0.03)).to(dev)[None].float()
    shifted = F0_alt.clone()
    if auto_f0:
        v_alt, v_ori = F0_alt[F0_alt > 1], F0_ori[F0_ori > 1]
        if v_alt.numel() and v_ori.numel():
            m_alt = torch.median(torch.log(v_alt + 1e-5))
            m_ori = torch.median(torch.log(v_ori + 1e-5))
            lf = torch.log(F0_alt + 1e-5).clone()
            lf[F0_alt > 1] = lf[F0_alt > 1] - m_alt + m_ori
            shifted = torch.exp(lf)
    cond, *_ = _S["model"].length_regulator(S_alt, ylens=tgt_len, n_quantizers=3, f0=shifted)
    pc, *_ = _S["model"].length_regulator(S_ori, ylens=tgt2, n_quantizers=3, f0=F0_ori)
    return cond, pc, mel2


def generate(sliders, carrier_b64=None, speed=None, pitch_variation=None, breathiness=None,
             faithful=False, cfg_rate=None, anchors=None):
    # faithful(学習素材用): AUTO_F0再センタリングを止め感情の音域差を保存、拡散ステップを増やし
    # 細部を残し、出力段DSPを掛けず、CFGを下げてターゲット引力を弱める。
    # SBV2学習で感情方向が潰れる問題への対策モード。
    _require_anchors()
    if not carrier_b64 and not os.path.exists(_carrier()):
        raise NotReady("元の音声がありません。録音するか、ファイルを選んでください")
    sv = {k: float(v) / 100.0 for k, v in sliders.items()}
    emb, top, w = design.design_embedding(sv, _S["bank"], allow=set(anchors) if anchors else None)
    sr = _S["sr"]
    dev = _S["device"]
    steps = FAITHFUL_STEPS if faithful else STEPS
    auto_f0 = (not faithful) and AUTO_F0
    # cfg_rate 明示指定が最優先（実験用）。無指定は faithful なら FAITHFUL_CFG、通常は CFG。
    cfg = float(cfg_rate) if cfg_rate is not None else (FAITHFUL_CFG if faithful else CFG)
    with torch.inference_mode():
        style = torch.tensor(emb, dtype=torch.float32, device=dev).reshape(1, -1)
        segs = []
        for n in top:
            p = _anchor_ref_path(n)
            if p and os.path.exists(p):
                y = librosa.load(p, sr=sr)[0]
                segs.append((y / (np.max(np.abs(y)) + 1e-9) * 0.9)[: int(PROMPT_S * sr)])
        cref = np.concatenate(segs) if segs else np.zeros(int(PROMPT_S * sr), np.float32)
        if F0_COND:
            carrier_path = b64_to_wav(carrier_b64) if carrier_b64 else _carrier()
            cond, pc, mel2 = _f0_cond_and_prompt(carrier_path, cref, sr, dev, auto_f0=auto_f0)
        else:
            if carrier_b64:
                cond = _cond_from_audio(b64_to_wav(carrier_b64))
            else:  # 既定キャリアは起動後に作られることもある（初回セットアップ）ので必要時に計算
                if "default_cond" not in _S:
                    _S["default_cond"] = _cond_from_audio(_carrier())
                cond = _S["default_cond"]
            cref_t = torch.tensor(cref).unsqueeze(0).float().to(dev)
            w16 = torchaudio.functional.resample(cref_t, sr, 16000)
            s_ori = _S["semantic_fn"](w16)
            mel2 = _S["mel_fn"](cref_t.float())
            pc, *_ = _S["model"].length_regulator(s_ori, ylens=torch.LongTensor([mel2.size(2)]).to(dev),
                                                  n_quantizers=3, f0=None)
        cat = torch.cat([pc, cond], dim=1)
        # 生成を決定論化: 同一入力(録音+スライダー)なら毎回同一の変換結果になる
        # （CFM が乱数ノイズからサンプリングするため、未固定だと実行毎に少し変わる）
        torch.manual_seed(1234)
        if dev.type == "cuda":
            torch.cuda.manual_seed_all(1234)
        with torch.autocast(device_type=dev.type, dtype=torch.float32):
            vt = _S["model"].cfm.inference(cat, torch.LongTensor([cat.size(1)]).to(dev),
                                           mel2, style, None, steps, inference_cfg_rate=cfg)
            vt = vt[:, :, mel2.size(-1):]
        wav = _S["vocoder_fn"](vt.float()).squeeze().detach().cpu().float().numpy().reshape(-1)
    # 後処理DSPは再生成なしで再適用できるよう、素の生成波形をテイクごとにキャッシュ
    take_id = _remember_raw(wav)
    # 忠実モード(学習素材用)はDSPを掛けず素の生成波形を返す（感情プロソディ保存）。
    out = wav if faithful else _dsp(wav, sr, speed, pitch_variation, breathiness)
    b64 = _wav_b64(out, sr)
    info = [{"name": n, "weight": float(wi)} for n, wi in
            sorted(zip(_S["bank"].names, w), key=lambda x: -x[1])[:3]]
    return {"wav_b64": b64, "sr": OUTPUT_SR or sr, "top": info, "faithful": faithful,
            "cfg_rate": cfg, "take_id": take_id}


# 画面で聴き比べるテイクの素波形。古いものから捨てる（1本あたり数百KB）
MAX_TAKES = 20


def _remember_raw(wav) -> int:
    raws = _S.setdefault("raws", {})
    _S["take_seq"] = _S.get("take_seq", 0) + 1
    raws[_S["take_seq"]] = wav.astype(np.float32).copy()
    while len(raws) > MAX_TAKES:
        raws.pop(min(raws))
    return _S["take_seq"]


def _dsp(wav, sr, speed=None, pitch_variation=None, breathiness=None):
    """出力段の後処理エフェクト（話速・ピッチ揺らぎ・息遣い）＋ピーク正規化。"""
    wav = _apply_speed(wav, speed)
    if pitch_variation is not None:
        wav = _apply_pitch_variation(wav, sr, min(max(float(pitch_variation) / 100.0, 0.0), 1.0))
    if breathiness is not None:
        wav = _apply_breathiness(wav, sr, min(max(float(breathiness) / 100.0, 0.0), 1.0))
    pk = float(np.max(np.abs(wav)))
    if pk > 0.97:
        wav = wav * (0.97 / pk)
    return wav


# 書き出しサンプルレート。GPT-SoVITS の参照音声は内部 32kHz のため既定 32000。
# 0 を指定すると変換せず生成モデルのネイティブSR(22.05kHz)のまま出力する。
OUTPUT_SR = int(os.environ.get("VOICE_CANVA_OUTPUT_SR", "32000"))


def _wav_b64(wav, sr) -> str:
    if OUTPUT_SR and sr != OUTPUT_SR:
        wav = librosa.resample(wav.astype(np.float32), orig_sr=sr, target_sr=OUTPUT_SR)
        sr = OUTPUT_SR
    buf = io.BytesIO()
    # 仕様準拠: 16bit PCM モノラル WAV（従来は32bit float だった）
    sf.write(buf, wav.astype(np.float32), sr, format="WAV", subtype="PCM_16")
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode()


def postprocess(speed=None, pitch_variation=None, breathiness=None, take_id=None):
    """テイクの素波形に後処理DSPのみ再適用（モデル再実行なし）。take_id 省略時は直近のテイク。"""
    raws = _S.get("raws") or {}
    if not raws:
        raise RuntimeError("まだ変換した音声がありません。先に変換してください")
    raw = raws.get(take_id if take_id is not None else max(raws))
    if raw is None:
        raise RuntimeError("このテイクは古くなったため仕上げ直せません（もう一度変換してください）")
    out = _dsp(raw, _S["sr"], speed, pitch_variation, breathiness)
    return {"wav_b64": _wav_b64(out, _S["sr"]), "sr": OUTPUT_SR or _S["sr"]}
