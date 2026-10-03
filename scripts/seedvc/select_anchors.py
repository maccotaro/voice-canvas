"""話者録音から「単一話者・落ち着いた」発話区間を選び、新規アンカーとして登録する。

従来の extract_stable は 4s 窓内の F0 微小安定性のみで選定していたため、
(1) 窓内で話者が交代する区間（対談/インタビュー音源）を弾けず、
(2) 感情の強い（抑揚・声量変動の大きい）区間を拾うことがあった。

本スクリプトは 2 段階で根本的に解決する:

  Stage1 (安価, pyin/RMS) — 各候補 4s 窓の「落ち着き＋安定性」を評価:
    - F0 微小安定性（隣接フレームの半音変動の中央値, 小=安定）
    - 有声確度（周期性の明瞭さ）
    - F0 スプレッド p90-p10 [半音]（広い=抑揚過多=感情的 → 減点）
    - RMS エネルギーの変動係数（大=声量変動=感情的 → 減点）
  Stage2 (campplus 話者埋め込み) — 上位候補の 12s 切り出し範囲を 2s チャンクに分割し、
    各チャンクの話者埋め込みのコサイン類似度（medoid への最小コサイン）で単一話者性を判定。
    話者交代があれば類似度が落ちるため除外できる。アンカー埋め込みと同一の campplus を
    用いるので、選定基準とアンカー定義が一貫する。

選定: 上位候補のうち単一話者しきい値を満たすものから最も落ち着いた窓を採用（ハード制約=単一
話者、優先=落ち着き）。満たすものが無ければ最も単一話者性の高い窓を採用し警告を出す。

各話者の 4s(分析用) と 12s(VCターゲット用) を data/ に、4s クリップの音響特徴を features/ に
書き出し、素材ファイル名との対応を data/anchor_sources.json に記録する。埋め込み(anchor_embeddings.npz)
は本スクリプト後に precompute_anchors.py で再計算する。

cwd=external/seed-vc 前提（from inference import ...）。
使い方:
    PYTHONPATH=.:$PROJ python select_anchors.py <src_dir> [--limit N] [--report] \
        [--homo-thresh 0.55] [--start-index 19]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import librosa  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import torchaudio  # noqa: E402

from inference import load_models  # noqa: E402  (Seed-VC, cwd=external/seed-vc)

PROJ = os.environ.get("VOICE_CANVA_PROJ") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJ)
DATA = os.path.join(PROJ, "data")
FEAT = os.path.join(PROJ, "features")
MANIFEST = os.path.join(DATA, "anchor_sources.json")

from voice_canva import anchor_select as sel  # noqa: E402  (選定ロジック本体。サービスと共用)
from voice_canva.anchor_select import GUARD_S, N_CAND, SR16, WIN_S  # noqa: E402,F401
from voice_canva.seedvc_device import configure_seedvc_device  # noqa: E402

device = configure_seedvc_device()   # load_models より前に呼ぶ（Mac で MPS を避ける）

_stage1_feats = sel.stage1_feats
_composite = sel.composite


def _embed(campplus, seg16: np.ndarray) -> np.ndarray:
    yt = torch.tensor(seg16).unsqueeze(0).float().to(device)
    feat = torchaudio.compliance.kaldi.fbank(yt, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    return campplus(feat.unsqueeze(0)).squeeze().detach().cpu().numpy()


def _select_best(campplus, y16: np.ndarray, homo_thresh: float, squim=None, pesq_thresh: float = 0.0):
    with torch.inference_mode():
        return sel.select_best(lambda seg: _embed(campplus, seg), y16, homo_thresh,
                               squim=squim, pesq_thresh=pesq_thresh)


# ---------------- 入出力 ----------------
def _next_spk_index() -> int:
    nums = []
    for p in glob.glob(os.path.join(DATA, "tgt_spk*_long.wav")):
        digits = "".join(filter(str.isdigit, os.path.basename(p)))
        if digits:
            nums.append(int(digits))
    return (max(nums) + 1) if nums else 1


def _cut_and_write(y: np.ndarray, sr: int, center_s: float, name: str) -> None:
    seg4, seg12 = sel.cut_windows(y, sr, center_s)
    sf.write(os.path.join(PROJ, f"data/{name}.wav"), seg4, sr, subtype="PCM_16")
    sf.write(os.path.join(PROJ, f"data/tgt_{name}_long.wav"), seg12, sr, subtype="PCM_16")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src_dir")
    ap.add_argument("--limit", type=int, default=0, help="先頭N件のみ処理（校正用）")
    ap.add_argument("--report", action="store_true", help="選定診断のみ。書き込まない")
    ap.add_argument("--homo-thresh", type=float, default=0.55, help="単一話者の最小コサイン")
    ap.add_argument("--pesq-thresh", type=float, default=2.3, help="録音品質(SQUIM PESQ推定)の最小値")
    ap.add_argument("--no-pesq", action="store_true", help="品質ゲートを無効化(SQUIM未使用)")
    ap.add_argument("--start-index", type=int, default=0, help="採番開始（0=既存最大+1）")
    ap.add_argument("--redo", default="", help="再選定する spk をカンマ区切りで指定（例 spk21,spk29）。"
                                              "対応表から元素材を引き、同じ番号で上書きする")
    ap.add_argument("--candidates", type=int, default=0,
                    help="各 redo 対象につき上位N個の時間分散した候補を data/_audition/ に書き出す（試聴用）。"
                         "単一話者しきい値は無視し全候補から選ぶ（homog は注記）")
    ap.add_argument("--pick", default="",
                    help="試聴後の確定。spk:center 形式をカンマ区切り（例 spk46:405,spk57:425）。"
                         "指定 center 秒を中心に切り出して確定する")
    args = ap.parse_args()

    from voice_canva import analysis

    print("▶ Seed-VC モデルロード中...", flush=True)
    a = argparse.Namespace(f0_condition=False, auto_f0_adjust=False, semi_tone_shift=0,
                           checkpoint=None, config=None, fp16=False)
    _model, _sem, _f0, _voc, campplus_model, _mel, _mel_args = load_models(a)

    squim = None
    if not args.no_pesq:
        from torchaudio.pipelines import SQUIM_OBJECTIVE
        squim = SQUIM_OBJECTIVE.get_model()
        squim.eval()
        print("▶ SQUIM(品質ゲート)ロード完了", flush=True)

    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)

    # 処理対象を (name, path) のリストとして決める
    if args.redo:
        targets = []
        for nm in [s.strip() for s in args.redo.split(",") if s.strip()]:
            base = manifest.get(nm)
            if not base:
                print(f"⚠️  {nm}: 対応表に元素材が無い→スキップ", flush=True)
                continue
            targets.append((nm, os.path.join(args.src_dir, base)))
    else:
        srcs = sorted(glob.glob(os.path.join(args.src_dir, "*.wav")))
        if args.limit:
            srcs = srcs[:args.limit]
        idx = args.start_index or _next_spk_index()
        targets = [(f"spk{idx + i}", p) for i, p in enumerate(srcs)]
    if not targets:
        print(f"❌ 処理対象がありません", flush=True)
        return 1

    # --- 試聴候補の書き出し（確定はしない） ---
    if args.candidates:
        audition = os.path.join(DATA, "_audition")
        os.makedirs(audition, exist_ok=True)
        for name, path in targets:
            if not os.path.exists(path):
                print(f"⚠️  {name}: 素材なし {path}", flush=True)
                continue
            y, sr = sf.read(path, dtype="float32")
            if y.ndim > 1:
                y = y.mean(axis=1)
            y16 = librosa.resample(y, orig_sr=sr, target_sr=SR16)
            win = int(WIN_S * SR16); guard = int(GUARD_S * SR16); hi = len(y16) - guard - win
            cands = []
            for p in np.linspace(guard, hi, N_CAND).astype(int):
                seg = y16[p:p + win]
                if float(np.max(np.abs(seg))) < 1e-3:
                    continue
                m = _stage1_feats(seg)
                if m:
                    cands.append({**m, "center": p / SR16})
            if not cands:
                continue
            modal = float(np.median([c["f0"] for c in cands]))
            for c in cands:
                c["modal_dev"] = abs(np.log2(c["f0"] / modal)) * 12.0
                c["score"] = _composite(c, modal)
            cands.sort(key=lambda c: -c["score"])
            # 時間的に 20s 以上離れた上位 N 候補を採る
            chosen = []
            for c in cands:
                if all(abs(c["center"] - o["center"]) >= 20.0 for o in chosen):
                    chosen.append(c)
                if len(chosen) >= args.candidates:
                    break
            print(f"\n{name} ({os.path.basename(path)}) modal={modal:.0f}Hz", flush=True)
            for k, c in enumerate(chosen, 1):
                with torch.inference_mode():
                    h = sel.homogeneity(lambda seg: _embed(campplus_model, seg), y16, c["center"])
                h = -1.0 if h is None else h
                start = max(0.0, c["center"] + 2.0 - 2.0)
                seg = y[int(start * sr):int(start * sr) + int(4.0 * sr)]
                seg = seg / (np.max(np.abs(seg)) + 1e-9) * 0.9
                out = os.path.join(audition, f"{name}_c{k}_{int(c['center'])}s.wav")
                sf.write(out, seg.astype("float32"), sr, subtype="PCM_16")
                print(f"  c{k}: @{c['center']:4.0f}s 単一話者={h:.2f} 抑揚={c['spread']:4.1f}半音 "
                      f"ホールド={c['hold']:.2f}s 音域差={c['modal_dev']:4.1f}半音 変動={c['ecv']:.2f} "
                      f"F0={c['f0']:.0f}Hz  → {os.path.basename(out)}", flush=True)
        print(f"\n試聴用クリップ: {audition}/  気に入った c の center 秒を --pick spkNN:秒 で確定してください。",
              flush=True)
        return 0

    # --- 試聴後の確定（center 指定で切り出し） ---
    if args.pick:
        for tok in [t.strip() for t in args.pick.split(",") if t.strip()]:
            nm, _, cs = tok.partition(":")
            center = float(cs)
            base = manifest.get(nm)
            if not base:
                print(f"⚠️  {nm}: 対応表に元素材なし→スキップ", flush=True)
                continue
            path = os.path.join(args.src_dir, base)
            y, sr = sf.read(path, dtype="float32")
            if y.ndim > 1:
                y = y.mean(axis=1)
            _cut_and_write(y, sr, center, nm)
            feat = analysis.analyze_wav(os.path.join(DATA, f"{nm}.wav"), name=nm)
            feat.save(os.path.join(FEAT, f"{nm}.npz"))
            print(f"✅ {nm} ← {base} @{center:.0f}s で確定", flush=True)
        print("\n確定完了。precompute_anchors.py で埋め込みを再計算してください。", flush=True)
        return 0

    os.makedirs(FEAT, exist_ok=True)
    added = 0
    low_homog = []
    for name, path in targets:
        base = os.path.basename(path)
        if not os.path.exists(path):
            print(f"⚠️  {name}: 素材が見つからない {path}→スキップ", flush=True)
            continue
        y, sr = sf.read(path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        y16 = librosa.resample(y, orig_sr=sr, target_sr=SR16)

        best, passed = _select_best(campplus_model, y16, args.homo_thresh,
                                    squim=squim, pesq_thresh=args.pesq_thresh)
        if best is None:
            print(f"⚠️  {base}: 候補なし→スキップ", flush=True)
            continue
        pesq = best.get("pesq", 0.0)
        low_q = squim is not None and pesq < args.pesq_thresh
        tag = ("" if passed else "  ⚠️単一話者しきい値未達") + ("  ⚠️品質しきい値未達" if low_q else "")
        if not passed or low_q:
            low_homog.append((name, base, best["homog"], pesq))

        print(f"{name} ← {base}  @{best['center']:.0f}s 単一話者={best['homog']:.2f} 品質PESQ={pesq:.2f} "
              f"抑揚={best['spread']:.1f}半音 ホールド={best['hold']:.2f}s 音域差={best['modal_dev']:.1f}半音 "
              f"F0={best['f0']:.0f}Hz{tag}", flush=True)

        if not args.report:
            _cut_and_write(y, sr, best["center"], name)
            feat = analysis.analyze_wav(os.path.join(DATA, f"{name}.wav"), name=name)
            feat.save(os.path.join(FEAT, f"{name}.npz"))
            manifest[name] = base
        added += 1

    if not args.report:
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {added} 件を{'再選定' if args.redo else '追加'}。対応表: {MANIFEST}", flush=True)
    else:
        print(f"\n[report] {added} 件を選定（書き込みなし）。", flush=True)
    if low_homog:
        print(f"\n⚠️ しきい値未達 {len(low_homog)} 件（単一話者<{args.homo_thresh} または 品質<{args.pesq_thresh}）:", flush=True)
        for nm, bs, h, q in low_homog:
            print(f"   {nm} ({bs}): 単一話者={h:.2f} 品質PESQ={q:.2f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
