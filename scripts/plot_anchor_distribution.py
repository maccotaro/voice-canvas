"""アンカーバンク全体の分布を可視化する。

(A) 8 意味軸ごとのアンカー分布（各軸 0..100% のストリッププロット＝設計空間のカバレッジ）
(B) campplus 話者埋め込み(192d)の PCA 2D 散布図（声質空間でのアンカーの広がり）

出力: output/anchor_distribution.png
依存: numpy / matplotlib（モデル不要）。voice_canva.design でバンクとスライダー値を取得。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJ)
from voice_canva import design  # noqa: E402

OUT = os.path.join(PROJ, "output", "anchor_distribution.png")


def _set_jp_font():
    for name in ["Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic", "Yu Gothic",
                 "AppleGothic", "Noto Sans CJK JP", "IPAexGothic"]:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.family"] = name
            return name
        except Exception:
            continue
    return None


def _labels(names):
    """anchor_sources.json があれば素材名、無ければ spk 名を短縮ラベルに。"""
    src = {}
    p = os.path.join(PROJ, "data", "anchor_sources.json")
    if os.path.exists(p):
        src = json.load(open(p, encoding="utf-8"))
    out = []
    for n in names:
        if n in src:
            lbl = src[n].replace("_128k.wav", "").replace(".wav", "")
            lbl = lbl.split("_")[0]            # 素材名の先頭部分
        else:
            lbl = n
        out.append(lbl)
    return out


def main():
    font = _set_jp_font()
    bank = design.load_bank()
    names = bank.names
    labels = _labels(names)
    sv = design.anchor_slider_values(bank)      # name -> [8軸 %]
    axes_keys = design.AXIS_KEYS
    axes_labels = [a.label for a in design.AXES]

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.05, 1])

    # (A) 8 軸カバレッジ（ストリップ）
    axA = fig.add_subplot(gs[0, 0])
    rng = np.random.default_rng(0)
    for i, key in enumerate(axes_keys):
        vals = np.array([sv[n][i] for n in names])
        y = np.full_like(vals, i, dtype=float) + (rng.random(len(vals)) - 0.5) * 0.5
        axA.scatter(vals, y, s=18, alpha=0.55, color="#3a76b4")
        axA.scatter(vals.mean(), i, s=90, marker="|", color="crimson", zorder=3)
    axA.set_yticks(range(len(axes_keys)))
    axA.set_yticklabels([f"{a.label}\n{a.low}↔{a.high}" for a in design.AXES], fontsize=9)
    axA.set_xlim(0, 100)
    axA.set_xlabel("スライダー値 (0–100%)")
    axA.set_title(f"(A) 意味軸ごとのアンカー分布  N={len(names)}（赤=平均）")
    axA.grid(axis="x", alpha=0.3)
    axA.invert_yaxis()

    # (B) 埋め込み PCA 2D
    axB = fig.add_subplot(gs[0, 1])
    X = np.asarray(bank.embeddings, float)
    Xc = X - X.mean(axis=0)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    Z = Xc @ Vt[:2].T
    ev = (S[:2] ** 2) / (S ** 2).sum() * 100
    # 性別軸(gender)で色付け（高=女性的）
    gi = list(axes_keys).index("gender")
    gcol = np.array([sv[n][gi] for n in names])
    scprime = axB.scatter(Z[:, 0], Z[:, 1], c=gcol, cmap="coolwarm", s=40, alpha=0.85,
                          edgecolors="white", linewidths=0.4)
    for (x, y), lb in zip(Z, labels):
        axB.annotate(lb, (x, y), fontsize=6, alpha=0.8,
                     xytext=(2, 2), textcoords="offset points")
    cb = fig.colorbar(scprime, ax=axB, fraction=0.046, pad=0.04)
    cb.set_label("性別軸 (青=男性的 / 赤=女性的)")
    axB.set_xlabel(f"PC1 ({ev[0]:.0f}%)")
    axB.set_ylabel(f"PC2 ({ev[1]:.0f}%)")
    axB.set_title("(B) 話者埋め込み(192d) の PCA 2D")
    axB.grid(alpha=0.3)

    fig.suptitle("声のCanva アンカー分布", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=110)
    print(f"font={font}  saved {OUT}  (anchors={len(names)})", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
