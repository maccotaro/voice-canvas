"""声のCanva MVP（Gradio）: 意味軸スライダーで声をデザイン → Seed-VC で生成 → 試聴/書き出し。

- 7 軸スライダー（較正済み5軸は有効、ラベル待ち2軸=知性/親近感 は無効表示）
- 「このパラメータで生成」: 設計→ブレンド埋め込み+近傍アンカー連結プロンプト→Seed-VC変換
- キャリア音声（プレビュー内容）を、設計した声で喋らせて試聴・wav書き出し

cwd=external/seed-vc 前提（Seed-VC のモデルは ./checkpoints）。
起動: HF_HUB_OFFLINE=1 PYTHONPATH=.:../.. ../../.venv-seedvc/bin/python app_canva.py
"""
from __future__ import annotations

import os
import sys

import librosa
import numpy as np
import torch
import torchaudio

_PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _PROJ)

from voice_canva import design  # noqa: E402
from inference import load_models  # noqa: E402
from voice_canva.seedvc_device import configure_seedvc_device  # noqa: E402

device = configure_seedvc_device()   # load_models より前に呼ぶ（Mac で MPS を避ける）

CARRIER = os.path.join(_PROJ, "data/spk2.wav")   # プレビュー内容（暫定: 既存クリップ）
OUTDIR = os.path.join(_PROJ, "output/canva")
STEPS = 30
CFG = 0.7
PROMPT_S = 4.0
USER_DIR = os.path.join(_PROJ, "data/user_anchors")   # 追加アンカーの永続保存先
MEM_FILE = os.path.join(_PROJ, "data/memory.json")     # メモリ設定の永続保存先

_STATE = {}


def _save_user_anchor(name, wav_src, emb, attr):
    """追加アンカー（録音wav＋埋め込み＋属性）をディスクへ永続保存。"""
    import json
    import shutil
    os.makedirs(USER_DIR, exist_ok=True)
    wav_dst = os.path.join(USER_DIR, f"{name}.wav")
    try:
        shutil.copyfile(wav_src, wav_dst)
    except Exception:
        wav_dst = wav_src
    np.savez(os.path.join(USER_DIR, f"{name}.npz"),
             embedding=np.asarray(emb, dtype=np.float32),
             formants=np.asarray(attr["formants"], dtype=np.float32))
    with open(os.path.join(USER_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump({k: float(attr[k]) for k in ("f0_mean", "hnr", "spectral_tilt", "shimmer", "jitter")}, f)
    return wav_dst


def _load_user_anchors():
    """永続化した追加アンカーを読み込む。→ [(name, embedding, attr, wav_path), ...]"""
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


def _load_memory():
    import json
    if os.path.exists(MEM_FILE):
        try:
            return json.load(open(MEM_FILE, encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_memory(state):
    import json
    with open(MEM_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def _args():
    import argparse
    a = argparse.Namespace()
    a.f0_condition = False; a.auto_f0_adjust = False; a.semi_tone_shift = 0
    a.checkpoint = None; a.config = None; a.fp16 = False
    return a


def _init():
    os.makedirs(OUTDIR, exist_ok=True)
    m = load_models(_args())
    model, semantic_fn, f0_fn, vocoder_fn, campplus_model, mel_fn, mel_fn_args = m
    sr = mel_fn_args["sampling_rate"]
    bank = design.load_bank()
    # キャリアの内容特徴(cond)を一度だけ計算
    src = librosa.load(CARRIER, sr=sr)[0]
    src_t = torch.tensor(src).unsqueeze(0).float().to(device)
    with torch.inference_mode():
        s_alt = semantic_fn(torchaudio.functional.resample(src_t, sr, 16000))
        mel = mel_fn(src_t.float())
        cond, *_ = model.length_regulator(s_alt, ylens=torch.LongTensor([mel.size(2)]).to(device),
                                          n_quantizers=3, f0=None)
    anchor_audio = {n: os.path.join(_PROJ, f"data/{n}.wav") for n in bank.names}
    # 永続化された追加アンカーを復元
    user_anchors = _load_user_anchors()
    for name, emb, attr, wav in user_anchors:
        bank = design.add_anchor(bank, name, emb, attr)
        anchor_audio[name] = wav
    _STATE.update(model=model, semantic_fn=semantic_fn, vocoder_fn=vocoder_fn,
                  campplus_model=campplus_model, mel_fn=mel_fn, sr=sr, bank=bank, cond=cond,
                  anchor_vals=design.anchor_slider_values(bank), anchor_audio=anchor_audio)
    print(f"[canva] 初期化完了 active軸: {bank.active_axes} "
          f"アンカー計{len(bank.names)}(うち追加{len(user_anchors)}) ラベル待ち: {design.axes_needing_labels()}")


def _anchor_ref_path(n):
    """プロンプト用の参照音声パス。組込みは長尺(tgt_)優先、追加アンカーは録音パス。"""
    long = os.path.join(_PROJ, f"data/tgt_{n}_long.wav")
    if os.path.exists(long):
        return long
    return _STATE.get("anchor_audio", {}).get(n) or os.path.join(_PROJ, f"data/{n}.wav")


def _concat_prompt(top_names, sr):
    segs = []
    for n in top_names:
        p = _anchor_ref_path(n)
        if not p or not os.path.exists(p):
            continue
        y = librosa.load(p, sr=sr)[0]
        y = y / (np.max(np.abs(y)) + 1e-9) * 0.9
        segs.append(y[: int(PROMPT_S * sr)])
    return np.concatenate(segs) if segs else np.zeros(int(PROMPT_S * sr), dtype=np.float32)


def _compute_cond(path):
    """録音/アップロード音声 → 内容特徴(cond)。変換元の言葉・タイミングを供給。"""
    st = _STATE
    sr = st["sr"]
    src = librosa.load(path, sr=sr)[0]
    src_t = torch.tensor(src).unsqueeze(0).float().to(device)
    with torch.inference_mode():
        s_alt = st["semantic_fn"](torchaudio.functional.resample(src_t, sr, 16000))
        mel = st["mel_fn"](src_t.float())
        cond, *_ = st["model"].length_regulator(
            s_alt, ylens=torch.LongTensor([mel.size(2)]).to(device), n_quantizers=3, f0=None)
    return cond


def generate(carrier, *slider_vals):
    """変換元音声(任意) + スライダー値 → 設計声を生成。"""
    sv = {k: float(v) / 100.0 for k, v in zip(design.AXIS_KEYS, slider_vals)}
    st = _STATE
    cond = _compute_cond(carrier) if carrier else st["cond"]
    emb, top, w = design.design_embedding(sv, st["bank"])
    sr = st["sr"]
    with torch.inference_mode():
        style = torch.tensor(emb, dtype=torch.float32, device=device).reshape(1, -1)
        cref = _concat_prompt(top, sr)
        cref_t = torch.tensor(cref).unsqueeze(0).float().to(device)
        w16 = torchaudio.functional.resample(cref_t, sr, 16000)
        s_ori = st["semantic_fn"](w16)
        mel2 = st["mel_fn"](cref_t.float())
        pc, *_ = st["model"].length_regulator(s_ori, ylens=torch.LongTensor([mel2.size(2)]).to(device),
                                              n_quantizers=3, f0=None)
        cat = torch.cat([pc, cond], dim=1)
        with torch.autocast(device_type=device.type, dtype=torch.float32):
            vt = st["model"].cfm.inference(cat, torch.LongTensor([cat.size(1)]).to(device),
                                           mel2, style, None, STEPS, inference_cfg_rate=CFG)
            vt = vt[:, :, mel2.size(-1):]
        wav = st["vocoder_fn"](vt.float()).squeeze().detach().cpu().float().numpy().reshape(-1)
    pk = float(np.max(np.abs(wav)))
    if pk > 0.97:
        wav = wav * (0.97 / pk)
    out = os.path.join(OUTDIR, "reference.wav")
    import soundfile as sf
    sf.write(out, wav.astype(np.float32), sr)
    info = "近いアンカー: " + ", ".join(f"{n}({wi*100:.0f}%)" for n, wi in
                                      sorted(zip(st["bank"].names, w), key=lambda x: -x[1])[:3])
    return (sr, wav), info, out


def analyze_to_sliders(carrier):
    """録音/アップロード音声を解析 → 各軸のスライダー位置(0..100)へ。"""
    import gradio as gr
    if not carrier:
        return [gr.update() for _ in design.AXIS_KEYS]
    from voice_canva import analysis
    f = analysis.analyze_wav(carrier)
    attr = dict(f0_mean=f.f0_mean, hnr=f.hnr, spectral_tilt=f.spectral_tilt,
                shimmer=f.shimmer, jitter=f.jitter, formants=f.formants)
    return design.slider_values_from_attrs(attr, _STATE["bank"])


def _embed_audio(path):
    """音声 → campplus 話者埋め込み(192,)。"""
    st = _STATE
    y = librosa.load(path, sr=st["sr"])[0]
    yt = torch.tensor(y[: int(st["sr"] * 25)]).unsqueeze(0).float().to(device)
    w16 = torchaudio.functional.resample(yt, st["sr"], 16000)
    feat = torchaudio.compliance.kaldi.fbank(w16, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    return st["campplus_model"](feat.unsqueeze(0)).squeeze().detach().cpu().numpy()


def add_recording_as_anchor(carrier, name):
    """録音をアンカーに追加して声空間を広げ、スライダーをその声に設定。"""
    import gradio as gr
    if not carrier:
        return [gr.update() for _ in design.AXIS_KEYS] + \
            ["⚠️ 先に録音/アップロードしてください", list(_STATE["bank"].names)]
    from voice_canva import analysis
    f = analysis.analyze_wav(carrier)
    attr = dict(f0_mean=float(f.f0_mean), hnr=float(f.hnr), spectral_tilt=float(f.spectral_tilt),
                shimmer=float(f.shimmer), jitter=float(f.jitter),
                formants=__import__("numpy").asarray(f.formants, float))
    with torch.inference_mode():
        emb = _embed_audio(carrier)
    st = _STATE
    nm = (name or "").strip() or f"my{sum(1 for n in st['bank'].names if n.startswith('my')) + 1}"
    st["bank"] = design.add_anchor(st["bank"], nm, emb, attr)
    st["anchor_vals"] = design.anchor_slider_values(st["bank"])
    # 永続保存（録音wav＋埋め込み＋属性）。再起動後も復元される。
    st["anchor_audio"][nm] = _save_user_anchor(nm, carrier, emb, attr)
    sliders = st["anchor_vals"][nm]
    msg = f"✅ 「{nm}」をアンカーに追加（計{len(st['bank'].names)}話者）。下部のボタンから選べます。"
    return sliders + [msg, list(st["bank"].names)]


def mem_save(name, state, *vals):
    """現在のスライダー値をセッションメモリに記憶。"""
    import gradio as gr
    state = list(state or [])
    nm = (name or "").strip() or f"メモリ{len(state) + 1}"
    state = [m for m in state if m["name"] != nm] + [{"name": nm, "vals": list(vals)}]
    _save_memory(state)
    names = [m["name"] for m in state]
    return state, gr.update(choices=names, value=nm)


def mem_recall(sel, state):
    """記憶した値でスライダーを戻す。"""
    import gradio as gr
    for m in (state or []):
        if m["name"] == sel:
            return m["vals"]
    return [gr.update() for _ in design.AXIS_KEYS]


def build():
    import gradio as gr

    need = set(design.axes_needing_labels())
    with gr.Blocks(title="声のCanva (Voice Canvas) β", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 声のCanva (Voice Canvas) β\n声のデザインを、もっと自由に。")
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 声のパラメータを調整する")
                sliders = []
                for ax in design.AXES:
                    disabled = ax.key in need
                    suffix = "　🔴ラベル付け待ち（未較正）" if disabled else ""
                    s = gr.Slider(0, 100, value=50, step=1,
                                  label=f"{ax.label}（{ax.low} ⇄ {ax.high}）{suffix}",
                                  interactive=not disabled)
                    sliders.append(s)
                btn = gr.Button("このパラメータで生成", variant="primary")
            with gr.Column(scale=1):
                gr.Markdown("### 変換元の音声（録音 or アップロード）")
                carrier = gr.Audio(sources=["microphone", "upload"], type="filepath",
                                   label="ここで喋った内容を、設計した声で生成します（空なら既定サンプル）")
                with gr.Row():
                    analyze_btn = gr.Button("🎙 この録音から軸を読み込む", size="sm")
                    addanchor_btn = gr.Button("🎤 この声をアンカーに追加（声空間を広げる）", size="sm")
                anchor_status = gr.Markdown()
                gr.Markdown("### プレビュー")
                audio = gr.Audio(label="生成された声", type="numpy")
                info = gr.Markdown()
                path = gr.Textbox(label="reference.wav 書き出し先", interactive=False)
                gr.Markdown(
                    "※ プレビュー内容は暫定キャリア音声（既存クリップ）。"
                    "知性・親近感は18話者のラベル付け後に有効化されます。")
        gr.Markdown("### メモリ（永続・記憶／呼び出し）")
        _mem0 = _load_memory()
        mem_state = gr.State(_mem0)
        with gr.Row():
            mem_name = gr.Textbox(label="メモリ名", placeholder="例: 理想の声A", scale=2)
            save_btn = gr.Button("💾 現在を記憶", scale=1)
            mem_dd = gr.Dropdown(choices=[m["name"] for m in _mem0], label="記憶した設定", scale=2)
            recall_btn = gr.Button("↩ この値でスライダーを戻す", scale=1)

        gr.Markdown("### アンカー（クリックで設定読み込み＋サンプル試聴）")
        anchor_preview = gr.Audio(label="アンカー試聴", type="filepath", autoplay=True)
        anchor_names_state = gr.State(list(_STATE["anchor_vals"].keys()))

        @gr.render(inputs=anchor_names_state)
        def _render_anchors(names):
            with gr.Row():
                for nm in names:
                    ab = gr.Button(nm, size="sm", min_width=70)
                    ab.click(fn=(lambda n=nm: _STATE["anchor_vals"][n] + [_STATE["anchor_audio"].get(n)]),
                             outputs=sliders + [anchor_preview])

        # 配線
        analyze_btn.click(analyze_to_sliders, inputs=[carrier], outputs=sliders)
        addanchor_btn.click(add_recording_as_anchor, inputs=[carrier, mem_name],
                            outputs=sliders + [anchor_status, anchor_names_state])
        save_btn.click(mem_save, inputs=[mem_name, mem_state] + sliders, outputs=[mem_state, mem_dd])
        recall_btn.click(mem_recall, inputs=[mem_dd, mem_state], outputs=sliders)
        btn.click(generate, inputs=[carrier] + sliders, outputs=[audio, info, path])
    return demo


if __name__ == "__main__":
    _init()
    build().launch(server_name="127.0.0.1", server_port=7861, show_api=False,
                   allowed_paths=[_PROJ])
