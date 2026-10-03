"""FreeVC PoC: 既存音声を別人/中間声へクリーン変換できるかの最小検証。

目的（ユーザー要件）:
- 汚い声を入力しても、無関係な別人と思える綺麗な声になること
- 実在しない「中間声」を、複数話者の話者埋め込みを**ベクトル補間**して作れること
  （素材混合ではなく埋め込み補間＝整合した新規話者）

coqui-tts(TTS) の FreeVC モデルを用いる。第1段階は単一ターゲットの any-to-any 変換、
第2段階は 2 話者の話者埋め込みを平均した「中間ターゲット」での変換。

実行:
    .venv-vc/bin/python scripts/poc_freevc.py
出力は output/vc/ に書き出す。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import soundfile as sf
import torch

OUT = "output/vc"
MODEL = "voice_conversion_models/multilingual/vctk/freevc24"


def _load_vc():
    from TTS.api import TTS

    # FreeVC の HiFi-GAN デコーダは出力チャンネル>65536 の conv を含み、MPS が非対応
    # （NotImplementedError）。短クリップなら CPU で十分高速なため CPU を用いる。
    dev = "cpu"
    tts = TTS(MODEL, progress_bar=False)
    tts.to(dev)
    print(f"[poc] device={dev}")
    return tts


def _speaker_embedding(vc_model, wav_path: str) -> torch.Tensor:
    """FreeVC の話者エンコーダで wav から話者埋め込み(d-vector, shape (1,D,1))を得る。

    coqui の FreeVC は ``_extract_target_se([wav])`` で話者埋め込みを計算する
    （use_spk なら外部話者エンコーダ、否なら mel + enc_spk）。
    """
    return vc_model._extract_target_se([wav_path])


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    tts = _load_vc()
    vc = tts.voice_converter  # SynthesizerTrn ラッパ
    model = vc.vc_model

    src_dirty = "data/spk3.wav"   # 採用した vocals-3 の 664s 区間を入力に
    tgt_a = "data/spk4.wav"       # 端点A: 最もクリア・中低音
    tgt_b = "data/spk2.wav"       # 端点B: 高音（最も異なる相手）
    out_sr = int(vc.output_sample_rate)

    # --- 第1段階: 単一ターゲットへの素の変換（クリーン/別人の確認）-----------
    for tag, tgt in [("to_spk4", tgt_a), ("to_spk2", tgt_b)]:
        out = f"{OUT}/poc_{tag}.wav"
        tts.voice_conversion_to_file(source_wav=src_dirty, target_wav=tgt, file_path=out)
        y, sr = sf.read(out)
        print(f"[poc] {tag}: {out} ({len(y)/sr:.1f}s sr={sr})")

    # --- 第2段階: 2話者埋め込みの補間 = 実在しない中間声 ---------------------
    # 素材を混ぜるのではなく、各話者を個別に埋め込み化し、ベクトルだけを補間する。
    ea = _speaker_embedding(model, tgt_a)   # (1,D,1)
    eb = _speaker_embedding(model, tgt_b)
    c = model.extract_wavlm_features(model.load_audio(src_dirty))
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        g = (1.0 - w) * ea + w * eb
        audio = model.inference(c, g=g)[0][0].data.cpu().float().numpy()
        out = f"{OUT}/poc_interp_{int(w * 100):03d}.wav"
        sf.write(out, audio.astype(np.float32), out_sr)
        print(f"[poc] interp spk4->spk2 w={w}: {out}")

    print("[poc] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
