"""Common Voice 日本語（CC0）からアンカー素材を用意する。

⚠️ Common Voice のダウンロード時には「データセット内の話者の身元を特定しない」ことに同意している。
   話者の特定につながる処理（話者照合で実在人物を推定する等）には使わないこと。

手順（3段）:
  1. select  : validated.tsv から性別×年代の枠ごとに録音量の多い話者を選び、必要なクリップの一覧を書く
       python scripts/cv_prepare.py select <cv_ja_dir> --out work/
       tar -xzf cv-corpus-*-ja.tar.gz -T work/clips.txt   # 一覧のクリップだけを展開
  2. concat  : 話者ごとにクリップ前後の無音を詰めて 1 本の wav にする（select_anchors.py の入力）
       python scripts/cv_prepare.py concat <cv_ja_dir> --out work/
     → work/speakers/cv_<性別><年代>_<n>.wav
     その後 seedvc/select_anchors.py work/speakers --start-index 1 > work/select.log
  3. pick    : select_anchors の結果から、品質しきい値を満たす話者を枠ごとに上位 N 人残し、
               残りを data/_excluded/ と features/_excluded/ へ退避する
       python scripts/cv_prepare.py pick work/select.log --per-bucket 3
     その後 seedvc/precompute_anchors.py で埋め込みを計算する

<cv_ja_dir> は展開した `cv-corpus-*/ja`（validated.tsv / clip_durations.tsv / reported.tsv / clips/ を含む）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import shutil

PROJ = os.environ.get("VOICE_CANVA_PROJ") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".."))

AGE = {"teens": "10", "twenties": "20", "thirties": "30", "fourties": "40", "fifties": "50",
       "sixties": "60", "seventies": "60", "eighties": "60", "nineties": "60"}
GENDER = {"female_feminine": "f", "male_masculine": "m"}


def _tsv(path: str):
    csv.field_size_limit(10 ** 9)
    with open(path, encoding="utf-8") as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


def cmd_select(a: argparse.Namespace) -> int:
    dur = {r["clip"]: int(r["duration[ms]"]) / 1000 for r in _tsv(os.path.join(a.cv_dir, "clip_durations.tsv"))}
    reported = {r["sentence_id"] for r in _tsv(os.path.join(a.cv_dir, "reported.tsv"))}
    clips = collections.defaultdict(list)
    for r in _tsv(os.path.join(a.cv_dir, "validated.tsv")):
        if r["sentence_id"] in reported or int(r["down_votes"] or 0) > 0:
            continue
        d = dur.get(r["path"], 0.0)
        if 2.0 <= d <= 10.0:
            clips[r["client_id"]].append((r["path"], d, r["gender"], r["age"]))

    buckets = collections.defaultdict(list)
    for cid, cs in clips.items():
        g = collections.Counter(c[2] for c in cs).most_common(1)[0][0]
        ag = collections.Counter(c[3] for c in cs).most_common(1)[0][0]
        total = sum(c[1] for c in cs)
        if g in GENDER and ag in AGE and total >= a.min_sec:
            buckets[GENDER[g] + AGE[ag]].append((total, cid, cs))

    sel = {}
    for b in sorted(buckets):
        for i, (_, cid, cs) in enumerate(sorted(buckets[b], reverse=True)[: a.per_bucket], 1):
            cs = sorted(cs, key=lambda c: -c[1])[: a.clips]
            sel[f"cv_{b}_{i}"] = {"client_id": cid, "clips": [c[0] for c in cs]}
        print(f"{b}: 候補 {len(buckets[b])} 人 → {min(len(buckets[b]), a.per_bucket)} 人", flush=True)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "selection.json"), "w", encoding="utf-8") as f:
        json.dump(sel, f, ensure_ascii=False, indent=1)
    base = os.path.relpath(os.path.join(a.cv_dir, "clips"), os.path.dirname(os.path.dirname(a.cv_dir)))
    with open(os.path.join(a.out, "clips.txt"), "w", encoding="utf-8") as f:
        f.writelines(f"{base}/{p}\n" for v in sel.values() for p in v["clips"])
    print(f"話者 {len(sel)} 人 / クリップ {sum(len(v['clips']) for v in sel.values())} 本 → {a.out}", flush=True)
    return 0


def _trim(y, sr: int, top_db: float = 35.0):
    import numpy as np
    hop = int(0.02 * sr)
    if len(y) < hop * 3:
        return y
    frames = len(y) // hop
    rms = np.sqrt(np.mean(y[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
    idx = np.where(20 * np.log10(rms / rms.max()) > -top_db)[0]
    if len(idx) == 0:
        return y[:0]
    return y[max(0, idx[0] - 2) * hop: min(len(y), (idx[-1] + 3) * hop)]


def cmd_concat(a: argparse.Namespace) -> int:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    sr_out = 44100
    gap = np.zeros(int(0.15 * sr_out), dtype=np.float32)
    sel = json.load(open(os.path.join(a.out, "selection.json"), encoding="utf-8"))
    out_dir = os.path.join(a.out, "speakers")
    os.makedirs(out_dir, exist_ok=True)
    for name, v in sel.items():
        parts = []
        for p in v["clips"]:
            fp = os.path.join(a.cv_dir, "clips", p)
            if not os.path.exists(fp):
                continue
            y, sr = sf.read(fp, dtype="float32", always_2d=True)
            y = y.mean(axis=1)
            if sr != sr_out:
                g = np.gcd(sr, sr_out)
                y = resample_poly(y, sr_out // g, sr // g).astype(np.float32)
            y = _trim(y, sr_out)
            if len(y) >= sr_out:
                parts += [y / (np.max(np.abs(y)) + 1e-9) * 0.7, gap]
        if not parts:
            print(f"{name}: クリップなし→スキップ", flush=True)
            continue
        y = np.concatenate(parts)
        sf.write(os.path.join(out_dir, f"{name}.wav"), y, sr_out, subtype="PCM_16")
        print(f"{name}: {len(y) / sr_out:.0f}s ({len(parts) // 2} クリップ)", flush=True)
    return 0


LOG_RE = re.compile(r"(spk\d+) ← cv_([fm]\d+)_\d+\.wav .*品質PESQ=([\d.]+)(.*)")


def cmd_pick(a: argparse.Namespace) -> int:
    buckets = collections.defaultdict(list)
    names = []
    for line in open(a.select_log, encoding="utf-8"):
        m = LOG_RE.match(line)
        if not m:
            continue
        name, bucket, pesq, tail = m.groups()
        names.append(name)
        if "未達" not in tail:
            buckets[bucket].append((float(pesq), name))
    keep = {n for b in buckets.values() for _, n in sorted(b, reverse=True)[: a.per_bucket]}

    data, feat = os.path.join(PROJ, "data"), os.path.join(PROJ, "features")
    os.makedirs(os.path.join(data, "_excluded"), exist_ok=True)
    os.makedirs(os.path.join(feat, "_excluded"), exist_ok=True)
    for n in names:
        if n in keep:
            continue
        for p in (os.path.join(data, f"{n}.wav"), os.path.join(data, f"tgt_{n}_long.wav")):
            if os.path.exists(p):
                shutil.move(p, os.path.join(data, "_excluded"))
        for f in os.listdir(feat):
            if f.startswith(n + "."):
                shutil.move(os.path.join(feat, f), os.path.join(feat, "_excluded"))
    print(f"採用 {len(keep)} 人 / 退避 {len(names) - len(keep)} 人（枠 {len(buckets)}）", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("cv_dir")
    s.add_argument("--out", default="work")
    s.add_argument("--per-bucket", type=int, default=6, help="枠ごとの候補話者数")
    s.add_argument("--clips", type=int, default=40, help="話者ごとのクリップ上限")
    s.add_argument("--min-sec", type=float, default=90.0, help="話者の最小合計秒数")
    c = sub.add_parser("concat")
    c.add_argument("cv_dir")
    c.add_argument("--out", default="work")
    p = sub.add_parser("pick")
    p.add_argument("select_log")
    p.add_argument("--per-bucket", type=int, default=3, help="枠ごとに残す話者数")
    a = ap.parse_args()
    return {"select": cmd_select, "concat": cmd_concat, "pick": cmd_pick}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
