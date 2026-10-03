"""CLI で作ったアンカー一式から、同梱用パック anchors/default/ を組み立てる。

入力（--src のプロジェクト）: data/tgt_spk*_long.wav, data/anchor_embeddings.npz, features/spk*.npz,
                               data/anchor_sources.json（spkN → 素材ファイル名 cv_<性別><年代>_<n>.wav）
任意: --select-log（select_anchors.py の出力。品質・単一話者スコアを記録に残す）, --carrier（既定の変換元音声）

同梱するのは 12 秒の参照音声(FLAC)・話者ベクトル・音響スカラだけ。features/*.npz の f0/sp/ap 配列
（元の声を再合成できる）は含めない。名前は Common Voice を 性別→年代 の順に spk1.. と振り直し、JVNV は jvnv_<話者>_<感情>。

使い方:
  python scripts/build_default_anchors.py --src ~/work/public-anchors \\
      --select-log ~/work/select.log --carrier ~/work/public-anchors/vocals/source_voice.wav
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys

import numpy as np
import soundfile as sf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

AGE_YEARS = {"10": 15, "20": 25, "30": 35, "40": 45, "50": 55, "60": 65}   # 年代の中央値（年齢感の軸に使う）
AGE = {"10": "10代", "20": "20代", "30": "30代", "40": "40代", "50": "50代", "60": "60代以上"}
SRC_RE = re.compile(r"cv_([fm])(\d+)_\d+")
JVNV_RE = re.compile(r"jvnv_([FM])(\d)_(\w+?)\.wav")
EMO = {"happy": "喜び", "sad": "悲しみ", "anger": "怒り", "fear": "恐れ", "disgust": "嫌悪", "surprise": "驚き"}
DATASETS = {
    "cv": {"name": "Common Voice 日本語 27.0", "license": "CC0-1.0"},
    "jvnv": {"name": "JVNV（日本語感情音声コーパス）", "license": "CC BY-SA 4.0",
             "credit": "Detai Xin, Junfeng Jiang, Shinnosuke Takamichi, Yuki Saito, Akiko Aizawa, Hiroshi Saruwatari. JVNV: A Corpus of Japanese Emotional Speech with Verbal Content and Nonverbal Expressions. arXiv:2310.06072, 2023."},
}
LOG_RE = re.compile(r"(spk\d+) ← .*単一話者=([\d.]+) 品質PESQ=([\d.]+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "anchors", "default"))
    ap.add_argument("--select-log", default="")
    ap.add_argument("--carrier", default="")
    a = ap.parse_args()

    from voice_canva.analysis import SpeakerFeatures

    d = np.load(os.path.join(a.src, "data", "anchor_embeddings.npz"), allow_pickle=True)
    names = [str(x) for x in d["names"]]
    embs = d["embeddings"].astype(np.float32)
    sources = json.load(open(os.path.join(a.src, "data", "anchor_sources.json"), encoding="utf-8"))
    quality = {}
    if a.select_log:
        for line in open(a.select_log, encoding="utf-8"):
            m = LOG_RE.match(line)
            if m:
                quality[m.group(1)] = (float(m.group(2)), float(m.group(3)))

    def sort_key(n: str):
        src = sources.get(n, "")
        m = SRC_RE.search(src)
        if m:
            return ("0", m.group(1), int(m.group(2)), "")
        j = JVNV_RE.search(src)
        if j:
            return ("1", j.group(1).lower(), int(j.group(2)), j.group(3))
        return ("2", "", 0, src)

    def label_of(n: str) -> tuple[str, str]:
        src = sources.get(n, "")
        m = SRC_RE.search(src)
        if m:
            return "cv", f"{'女性' if m.group(1) == 'f' else '男性'}・{AGE.get(m.group(2), m.group(2))}"
        j = JVNV_RE.search(src)
        if j:
            who = f"{'女性' if j.group(1) == 'F' else '男性'}{'AB'[int(j.group(2)) - 1]}"
            return "jvnv", f"{who}・{EMO.get(j.group(3), j.group(3))}（JVNV）"
        return "other", "話者"

    order = sorted(names, key=lambda n: (sort_key(n), int(n[3:])))
    used = {label_of(n)[0] for n in order}

    # 名前を固定する: 前回のパックと埋め込みが一致するアンカーは前回の名前のまま（展開済みの環境と
    # 食い違わないように）。新しく加わる Common Voice の話者は cv_<性別><年代>_<n>（画面から追加する
    # spkN と重ならない名前）にする。
    prev = {}
    prev_emb = os.path.join(a.out, "embeddings.npz")
    if os.path.exists(prev_emb):
        pe = np.load(prev_emb, allow_pickle=True)
        prev = {str(n): v for n, v in zip(pe["names"], pe["embeddings"])}

    def prev_name(vec):
        for n, v in prev.items():
            if np.allclose(v, vec, atol=1e-6):
                return n
        return None
    # 生成物（音声・埋め込み・manifest）は一時フォルダに全部作ってから入れ替える。途中で失敗しても
    # 既存のパックは壊れない。LICENSE.md など手書きのファイルは残す
    final_out = a.out
    a.out = os.path.join(os.path.dirname(final_out), ".build_tmp")
    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    os.makedirs(os.path.join(a.out, "audio"))

    anchors, new_embs = [], []
    taken = set()
    bucket_n: dict[str, int] = {}
    for old in order:
        ds_, _ = label_of(old)
        j = JVNV_RE.search(sources.get(old, ""))
        m = SRC_RE.search(sources.get(old, ""))
        kept = prev_name(embs[names.index(old)])
        if kept and kept not in taken:
            new = kept
        elif ds_ == "jvnv" and j:   # 専用の名前（画面から追加したアンカーの spkN と重ならない）
            new = f"jvnv_{j.group(1).lower()}{j.group(2)}_{j.group(3)}"
        elif m:
            b = f"{m.group(1)}{m.group(2)}"
            k = bucket_n.get(b, 3) + 1
            while f"cv_{b}_{k}" in prev or f"cv_{b}_{k}" in taken:
                k += 1
            bucket_n[b] = k
            new = f"cv_{b}_{k}"
        else:
            new = f"anchor_{old}"
        taken.add(new)
        y, sr = sf.read(os.path.join(a.src, "data", f"tgt_{old}_long.wav"), dtype="float32")
        sf.write(os.path.join(a.out, "audio", f"{new}.flac"), y, sr, format="FLAC", subtype="PCM_16")
        f = SpeakerFeatures.load(os.path.join(a.src, "features", f"{old}.npz"))
        ds, label = label_of(old)
        item = {"name": new, "label": label, "dataset": ds, "f0": round(float(f.f0_mean)),
                "attrs": {"f0_mean": float(f.f0_mean), "hnr": float(f.hnr), "spectral_tilt": float(f.spectral_tilt),
                          "shimmer": float(f.shimmer), "jitter": float(f.jitter),
                          "formants": [float(x) for x in np.asarray(f.formants, float)]}}
        m_cv = SRC_RE.search(sources.get(old, ""))
        if m_cv and m_cv.group(2) in AGE_YEARS:
            item["attrs"]["age"] = AGE_YEARS[m_cv.group(2)]
        if old in quality:
            item["single"], item["quality"] = round(quality[old][0], 2), round(quality[old][1], 2)
        anchors.append(item)
        new_embs.append(embs[names.index(old)])
        print(f"{old} → {new}  {label}", flush=True)

    np.savez(os.path.join(a.out, "embeddings.npz"), names=np.array([x["name"] for x in anchors]),
             embeddings=np.stack(new_embs))
    manifest = {"datasets": {k: v for k, v in DATASETS.items() if k in used},
                "built": datetime.date.today().isoformat(), "anchors": anchors}
    if a.carrier:
        y, sr = sf.read(a.carrier, dtype="float32")
        sf.write(os.path.join(a.out, "carrier.flac"), y, sr, format="FLAC", subtype="PCM_16")
        manifest["carrier"] = "carrier.flac"
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=1)
    for item in ("audio", "embeddings.npz", "manifest.json", "carrier.flac"):
        src, dst = os.path.join(a.out, item), os.path.join(final_out, item)
        if not os.path.exists(src):
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        elif os.path.exists(dst):
            os.remove(dst)
        shutil.move(src, dst)
    shutil.rmtree(a.out)
    print(f"✅ {len(anchors)} 人 → {final_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
