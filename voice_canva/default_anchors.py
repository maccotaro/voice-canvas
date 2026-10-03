"""同梱のアンカー一式（anchors/default/）を data/ に展開する。インストール直後から声を作れるようにする。

初回起動（data/ にアンカーが無い）なら全員を展開する。すでに展開済みなら、パックに増えたアンカーのうち
まだ data/ に無いものだけを追加する（利用者が外したアンカー＝_excluded にあるものは戻さない）。
利用者が登録・退避したアンカーは上書きしない。

パックの中身:
  manifest.json   : アンカーごとの名前・表示用ラベル・品質記録・音響スカラ、キャリア音声のファイル名
  embeddings.npz  : 話者ベクトル（names, embeddings）
  audio/<name>.flac : 12 秒の参照音声（生成時のお手本）。4 秒の試聴・分析用はこの 4〜8 秒目を切り出す
  carrier.flac    : 既定の変換元音声（録音しないで試すとき用）
"""
from __future__ import annotations

import json
import os
from glob import glob as _glob

import numpy as np
import soundfile as sf

SHORT_OFFSET_S = 4.0   # 12 秒の中の 4 秒区間の開始位置（anchor_select.cut_windows と同じ配置）
SHORT_S = 4.0


def pack_dir(proj: str) -> str:
    return os.path.join(proj, "anchors", "default")


def bundled_names(proj: str) -> set[str]:
    """同梱パックに入っているアンカー名。これらは外せるが、完全には削除させない（いつでも戻せるように）。"""
    path = os.path.join(pack_dir(proj), "manifest.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {a["name"] for a in json.load(f)["anchors"]}


def install(proj: str) -> int:
    """必要なら展開し、展開したアンカー数を返す（展開しなかったら 0）。"""
    pack = pack_dir(proj)
    data = os.path.join(proj, "data")
    manifest_path = os.path.join(pack, "manifest.json")
    if not os.path.exists(manifest_path):
        return 0
    from voice_canva import design

    emb_path = os.path.join(data, "anchor_embeddings.npz")
    have: list[str] = []
    have_vecs = None
    if os.path.exists(emb_path):
        d = np.load(emb_path, allow_pickle=True)
        have, have_vecs = [str(x) for x in d["names"]], d["embeddings"].astype(np.float32)
    excluded = {os.path.basename(p)[4:-9] for p in _glob(os.path.join(data, "_excluded", "tgt_*_long.wav"))}

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    _backfill_labels(manifest["anchors"], have)
    manifest["anchors"] = [a for a in manifest["anchors"] if a["name"] not in have and a["name"] not in excluded]
    if not manifest["anchors"]:
        return 0
    # 欠けたパックで半端に展開しない（サービスは空のまま起動し、画面から登録できる）
    need = ["embeddings.npz"] + [os.path.join("audio", f"{a['name']}.flac") for a in manifest["anchors"]]
    if manifest.get("carrier"):
        need.append(manifest["carrier"])
    missing = [p for p in need if not os.path.exists(os.path.join(pack, p))]
    if missing:
        print(f"[voice-canva] ⚠️ 同梱アンカーのファイルが足りないため展開しません: {missing[:3]}", flush=True)
        return 0
    os.makedirs(data, exist_ok=True)

    sources, meta, attrs = {}, {}, {}
    for a in manifest["anchors"]:
        n = a["name"]
        y, sr = sf.read(os.path.join(pack, "audio", f"{n}.flac"), dtype="float32")
        sf.write(os.path.join(data, f"tgt_{n}_long.wav"), y, sr, subtype="PCM_16")
        i0 = int(SHORT_OFFSET_S * sr)
        short = y[i0:i0 + int(SHORT_S * sr)]
        short = short / (np.max(np.abs(short)) + 1e-9) * 0.9
        sf.write(os.path.join(data, f"{n}.wav"), short.astype("float32"), sr, subtype="PCM_16")
        sources[n] = a["label"]
        meta[n] = {k: a[k] for k in ("quality", "single", "f0") if k in a} | {"source": a["label"],
                                                                              "added": manifest.get("built", "")}
        attrs[n] = {**{k: float(a["attrs"][k]) for k in design.ATTR_KEYS},
                    "formants": np.asarray(a["attrs"]["formants"], float),
                    **{k: float(a["attrs"][k]) for k in design.OPTIONAL_KEYS if a["attrs"].get(k) is not None}}
    design.write_attrs(attrs)
    for name, obj in (("anchor_sources.json", sources), ("anchor_meta.json", meta)):
        path = os.path.join(data, name)
        cur = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cur = json.load(f)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({**cur, **obj}, f, ensure_ascii=False, indent=1)

    carrier = manifest.get("carrier")
    if carrier and not os.path.exists(os.path.join(data, "carrier.wav")):
        y, sr = sf.read(os.path.join(pack, carrier), dtype="float32")
        sf.write(os.path.join(data, "carrier.wav"), y, sr, subtype="PCM_16")
    # 埋め込みは最後に書く（途中で失敗しても「未展開」のまま残り、次回起動で展開し直せる）
    pk = np.load(os.path.join(pack, "embeddings.npz"), allow_pickle=True)
    pnames = [str(x) for x in pk["names"]]
    add = [a["name"] for a in manifest["anchors"]]
    vecs = np.stack([pk["embeddings"][pnames.index(n)] for n in add]).astype(np.float32)
    if have:
        add, vecs = have + add, np.vstack([have_vecs, vecs])
    tmp = emb_path + ".tmp.npz"
    np.savez(tmp, names=np.array(add), embeddings=vecs)
    os.replace(tmp, emb_path)
    return len(manifest["anchors"])


def _backfill_labels(pack_anchors: list[dict], have: list[str]) -> None:
    """展開済みのアンカーに、パック側で増えたラベル（年齢など）を補う。音響の値は変えない。"""
    from voice_canva import design

    cur = design.read_attrs()
    updates = {}
    for a in pack_anchors:
        n = a["name"]
        if n not in have or n not in cur:
            continue
        add = {k: a["attrs"][k] for k in design.OPTIONAL_KEYS if a["attrs"].get(k) is not None and k not in cur[n]}
        if add:
            updates[n] = {**cur[n], **add}
    if updates:
        design.write_attrs(updates)
