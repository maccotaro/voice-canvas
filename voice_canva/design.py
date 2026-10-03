"""声のCanva — 意味軸スライダー → アンカー重み → ブレンド埋め込み（MVP コア）。

7 つの「解釈可能な軸」のスライダー値から、アンカー(実在話者のクリーン録音)の中で目標属性に
最も合う重み配分を求め、Seed-VC へ渡すブレンド埋め込みと近傍アンカー(プロンプト用)を返す。

軸は3状態:
- measured : 実測の音響属性で定義（F0/HNR/スペクトル傾斜/shimmer 等）
- approx   : 実測の近似（複合・要検証）
- needs_label : 客観指標がなく人手ラベルが必要（未較正。ラベルが無い間はマッチングから除外）

属性は features/spkN.npz（SpeakerFeatures）から、埋め込みは data/anchor_embeddings.npz から読む。
依存は numpy のみ（torch 不要）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

_PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_EMB = os.path.join(_PROJ, "data/anchor_embeddings.npz")
_FEAT_DIR = os.path.join(_PROJ, "features")
_LABELS = os.path.join(_PROJ, "data/anchor_labels.json")  # 主観軸の人手ラベル（任意）
# アンカーの音響スカラ（f0_mean/hnr/spectral_tilt/shimmer/jitter/formants）。
# features/*.npz は再合成できる配列(f0/sp/ap)を含むため、同梱・画面登録のアンカーはこちらだけを持つ。
_ATTRS = os.path.join(_PROJ, "data/anchor_attrs.json")

MEASURED = "measured"
APPROX = "approx"
NEEDS_LABEL = "needs_label"

# スライダー位置 ⇄ z スコアのマップ幅 [σ]。大きいほど端に張り付きにくい（外れ声に寛容）。
SLIDER_SPREAD = 2.5

# 1 つの声に混ぜるアンカーの人数（重みの大きい順）。全員を薄く混ぜると平均的な声に寄り、
# どの設定でも似た声になる（36 人だと実質 8〜14 人ぶんの平均だった）。4 人なら実質 3〜4 人の
# 混ぜ合わせで、1 人の声そのものにはならず、個性は残る。
BLEND_TOP = 4

# ラベル軸（label_key）を使うのに必要な、ラベル付きアンカーの最小人数。未満なら音響近似に戻す。
MIN_LABELED = 6

# 生成に必要な最小アンカー数。これ未満だと重み付けの母集団統計が成り立たない。
MIN_ANCHORS = 3


@dataclass(frozen=True)
class Axis:
    key: str
    label: str
    low: str
    high: str
    status: str
    # measured/approx: z正規化した音響特徴の線形結合（大きいほど high 側）。
    # 例 {"f0": 1.0, "formant": 1.0} → z(f0)+z(formant)
    features: dict = field(default_factory=dict)
    unit: str = ""
    # アンカーの実測ラベル（例: 年齢）を使う軸。ラベルが十分あれば features より優先する
    label_key: str = ""
    # 声を選ぶときの距離での重み。性別は他の 7 軸と同じ重みだと、ほかを中間にしたとき反対の性別の
    # アンカーが半分近く混ざったため 2 倍にする
    weight: float = 1.0


# 利用可能な音響特徴（アンカー属性 dict → スカラ。z 正規化は load_bank で行う）
def _feat_values(attrs: list[dict]) -> dict[str, np.ndarray]:
    fm = np.array([float(np.nanmean(a["formants"])) for a in attrs])
    return {
        "f0": np.log2(np.array([max(a["f0_mean"], 1e-6) for a in attrs])),
        "formant": np.log2(np.maximum(fm, 1e-6)),
        "hnr": np.array([a["hnr"] for a in attrs]),
        "tilt": np.array([a["spectral_tilt"] for a in attrs]),
        "shimmer": np.array([a["shimmer"] for a in attrs]),
        "jitter": np.array([a["jitter"] for a in attrs]),
    }


AXES: tuple[Axis, ...] = (
    # 年齢感: アンカーの実年齢（Common Voice の申告年代）で決める。「低い声＝年配」の音響近似は
    # 実年代との相関が r≈0.1 しかなかった（若い低い声が「年配」に選ばれていた）ため、ラベルが無いときの予備。
    Axis("age", "年齢感", "若い", "年配", APPROX, {"f0": -1.0, "formant": -0.5}, "歳", label_key="age"),
    Axis("gender", "性別", "男性的", "女性的", MEASURED, {"f0": 1.0, "formant": 1.0}, "%", weight=2.0),
    Axis("pitch", "声の高さ", "低い", "高い", MEASURED, {"f0": 1.0}, "%"),
    Axis("build", "体格", "太い", "細い", MEASURED, {"formant": 1.0}, "%"),
    Axis("huskiness", "ハスキー度", "クリア", "ハスキー", MEASURED, {"shimmer": 1.0, "hnr": -0.5}, "%"),
    Axis("clarity", "明瞭度", "こもる", "明瞭", MEASURED, {"hnr": 1.0}, "%"),
    Axis("warmth", "温かさ", "クール", "ウォーム", MEASURED, {"tilt": -1.0}, "%"),
    Axis("roughness", "粗さ", "なめらか", "ガラガラ", MEASURED, {"jitter": 1.0, "shimmer": 0.5}, "%"),
)
AXIS_KEYS = tuple(a.key for a in AXES)


def axes_needing_labels() -> list[str]:
    """現在ラベル付けが必要な軸キー（較正されていない＝マッチングに使えない）。"""
    labels = _load_labels()
    out = []
    for a in AXES:
        if a.status == NEEDS_LABEL and a.key not in labels:
            out.append(a.key)
    return out


def _load_labels() -> dict[str, dict[str, float]]:
    """data/anchor_labels.json: {axis_key: {anchor_name: value(0..1)}}。無ければ空。"""
    if os.path.exists(_LABELS):
        with open(_LABELS, encoding="utf-8") as f:
            return json.load(f)
    return {}


@dataclass
class AnchorBank:
    names: list[str]
    embeddings: np.ndarray                 # (N, 192)
    attrs: list[dict]                      # 各アンカーの素属性
    axis_z: dict[str, np.ndarray]          # 軸key -> (N,) z-score（定義済み軸のみ）
    active_axes: list[str] = field(default_factory=list)   # 現在マッチングに使える軸
    feat_stats: dict = field(default_factory=dict)         # feature -> (mean, std) アンカー母集団
    axis_stats: dict = field(default_factory=dict)         # axis_key -> (mean, std) 軸合成値の統計


def _raw_feats_one(attr: dict) -> dict[str, float]:
    """1 話者の素属性 → 音響特徴スカラ（_feat_values の単体版）。"""
    fm = float(np.nanmean(attr["formants"]))
    return {
        "f0": float(np.log2(max(attr["f0_mean"], 1e-6))),
        "formant": float(np.log2(max(fm, 1e-6))),
        "hnr": float(attr["hnr"]),
        "tilt": float(attr["spectral_tilt"]),
        "shimmer": float(attr["shimmer"]),
        "jitter": float(attr["jitter"]),
    }


ATTR_KEYS = ("f0_mean", "hnr", "spectral_tilt", "shimmer", "jitter")


OPTIONAL_KEYS = ("age",)   # 任意のラベル（年齢[歳] など）。無いアンカーもある


def attrs_to_json(attr: dict) -> dict:
    out = {**{k: float(attr[k]) for k in ATTR_KEYS},
           "formants": [float(x) for x in np.asarray(attr["formants"], float)]}
    out.update({k: float(attr[k]) for k in OPTIONAL_KEYS if attr.get(k) is not None})
    return out


def read_attrs() -> dict[str, dict]:
    """data/anchor_attrs.json → {name: 素属性}。無ければ空。"""
    if not os.path.exists(_ATTRS):
        return {}
    with open(_ATTRS, encoding="utf-8") as f:
        raw = json.load(f)
    return {n: {**{k: float(v[k]) for k in ATTR_KEYS}, "formants": np.asarray(v["formants"], float),
                **{k: float(v[k]) for k in OPTIONAL_KEYS if v.get(k) is not None}}
            for n, v in raw.items()}


def write_attrs(updates: dict[str, dict]) -> None:
    """data/anchor_attrs.json に名前ごとの素属性を書き足す（既存は保持）。"""
    cur = {}
    if os.path.exists(_ATTRS):
        with open(_ATTRS, encoding="utf-8") as f:
            cur = json.load(f)
    cur.update({n: attrs_to_json(a) for n, a in updates.items()})
    os.makedirs(os.path.dirname(_ATTRS), exist_ok=True)
    tmp = _ATTRS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ATTRS)


def remove_attrs(names) -> None:
    """data/anchor_attrs.json から名前ごとの素属性を消す（アンカーを完全に削除するとき）。"""
    if not os.path.exists(_ATTRS):
        return
    with open(_ATTRS, encoding="utf-8") as f:
        cur = json.load(f)
    for n in names:
        cur.pop(n, None)
    tmp = _ATTRS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ATTRS)


def empty_bank() -> AnchorBank:
    """アンカーが1件も無い状態（初回セットアップ前）。"""
    return AnchorBank([], np.zeros((0, 192)), [], {}, [], {}, {})


def load_bank() -> AnchorBank:
    """data/anchor_embeddings.npz と features/*.npz からバンクを作る。無ければ空のバンク。"""
    from voice_canva.analysis import SpeakerFeatures

    if not os.path.exists(_EMB):
        return empty_bank()
    d = np.load(_EMB, allow_pickle=True)
    names = [str(x) for x in d["names"]]
    embeddings = d["embeddings"].astype(np.float64)

    scal = read_attrs()
    attrs = []
    for n in names:
        if n in scal:
            attrs.append(scal[n])
            continue
        f = SpeakerFeatures.load(os.path.join(_FEAT_DIR, f"{n}.npz"))
        attrs.append(dict(
            f0_mean=float(f.f0_mean), hnr=float(f.hnr),
            spectral_tilt=float(f.spectral_tilt), shimmer=float(f.shimmer),
            jitter=float(f.jitter), formants=np.asarray(f.formants, float),
        ))

    return build_bank(names, embeddings, attrs)


def build_bank(names: list[str], embeddings: np.ndarray, attrs: list[dict]) -> AnchorBank:
    """names/埋め込み/属性 から AnchorBank を構築（z 正規化・統計を計算）。

    アンカーを追加した際に再構築するためにも使う（母集団が変われば統計も更新）。
    """
    embeddings = np.asarray(embeddings, float)
    # 各音響特徴を z 正規化（母集団の mean/std を保持し、新規音声も同基準で評価可能に）
    raw = _feat_values(attrs)
    feat_stats = {k: (float(v.mean()), float(v.std() or 1.0)) for k, v in raw.items()}
    zfeat = {k: (v - feat_stats[k][0]) / feat_stats[k][1] for k, v in raw.items()}

    labels = _load_labels()
    axis_z: dict[str, np.ndarray] = {}
    axis_stats: dict[str, tuple] = {}
    active: list[str] = []
    for ax in AXES:
        known = [a.get(ax.label_key) for a in attrs] if ax.label_key else []
        n_known = sum(v is not None for v in known)
        if ax.label_key and n_known >= MIN_LABELED:
            # 実測ラベルで決める。ラベルの無いアンカー（年齢不明）は母集団の平均＝中立に置く
            mean_known = float(np.mean([v for v in known if v is not None]))
            vals = np.array([mean_known if v is None else float(v) for v in known], float)
        elif ax.status in (MEASURED, APPROX) and ax.features:
            vals = np.asarray(sum(w * zfeat[f] for f, w in ax.features.items()), float)
        elif ax.key in labels:  # ラベル付与済みの主観軸
            vals = np.array([labels[ax.key].get(n, np.nan) for n in names], float)
            if np.isnan(vals).any():
                continue
        else:
            continue  # 未較正（ラベル待ち）→ マッチングに使わない
        mean, std = float(vals.mean()), float(vals.std() or 1.0)
        axis_stats[ax.key] = (mean, std)
        axis_z[ax.key] = (vals - mean) / std
        active.append(ax.key)

    return AnchorBank(names, embeddings, attrs, axis_z, active, feat_stats, axis_stats)


def add_anchor(bank: AnchorBank, name: str, embedding: np.ndarray, attr: dict) -> AnchorBank:
    """録音等の声を新アンカーとして加え、バンクを再構築して返す（声空間を広げる）。"""
    names = bank.names + [name]
    embeddings = np.vstack([bank.embeddings, np.asarray(embedding, float).reshape(1, -1)])
    attrs = bank.attrs + [attr]
    return build_bank(names, embeddings, attrs)


def remove_anchor(bank: AnchorBank, name: str) -> AnchorBank:
    """アンカーを外してバンクを再構築する（母集団統計も更新）。"""
    keep = [i for i, n in enumerate(bank.names) if n != name]
    if not keep:
        return empty_bank()
    return build_bank([bank.names[i] for i in keep], bank.embeddings[keep], [bank.attrs[i] for i in keep])


def slider_values_from_attrs(attr: dict, bank: AnchorBank, spread: float = SLIDER_SPREAD) -> list[float]:
    """1 音声の素属性 → スライダー位置(0..100)。録音/アップロード音声の解析に使う。

    アンカー母集団の統計(feat_stats/axis_stats)で同基準に z 正規化し、anchor_slider_values と
    同じマップでスライダー%へ。未較正(ラベル待ち)軸は 50。
    """
    raw = _raw_feats_one(attr)
    zf = {k: (raw[k] - bank.feat_stats[k][0]) / bank.feat_stats[k][1] for k in raw}
    out = []
    for ax in AXES:
        if ax.label_key and sum(a.get(ax.label_key) is not None for a in bank.attrs) >= MIN_LABELED:
            out.append(50.0)   # 実測ラベルの軸（年齢など）は録音の音響からは推定しない
        elif ax.key in bank.axis_stats and ax.features:
            vals = sum(w * zf[f] for f, w in ax.features.items())
            mean, std = bank.axis_stats[ax.key]
            z = (vals - mean) / std
            pct = (z / spread + 1.0) / 2.0 * 100.0
            out.append(float(np.clip(pct, 0.0, 100.0)))
        else:
            out.append(50.0)
    return out


def design_weights(slider_values: dict[str, float], bank: AnchorBank,
                   temp: float = 0.3, spread: float = SLIDER_SPREAD) -> np.ndarray:
    """スライダー値(0..1) → アンカー重み(softmax)。

    各 active 軸について、スライダー値を ±spread σ の目標 z にマップし、アンカーの
    属性 z との二乗距離を合計、softmax(-d/temp) で重みにする。未較正軸は無視。
    """
    n = len(bank.names)
    if not bank.active_axes:
        return np.full(n, 1.0 / n)
    d2 = np.zeros(n)
    wsum = 0.0
    weights = {a.key: a.weight for a in AXES}
    for key in bank.active_axes:
        s = float(np.clip(slider_values.get(key, 0.5), 0.0, 1.0))
        target = (2.0 * s - 1.0) * spread
        wt = weights.get(key, 1.0)
        d2 += wt * (bank.axis_z[key] - target) ** 2
        wsum += wt
    d2 /= wsum
    w = np.exp(-d2 / temp)
    return w / w.sum()


def anchor_slider_values(bank: AnchorBank, spread: float = SLIDER_SPREAD) -> dict[str, list[float]]:
    """各アンカーの実測属性を「スライダー位置(0..100)」へ逆算する。

    クリックでその話者の設定を読み込む用途。較正済み軸は z スコアを ±spread σ →
    0..100% にマップ（design_weights の目標マップの逆）。未較正(ラベル待ち)軸は 50。
    戻り値: name -> AXIS_KEYS 順の % リスト。
    """
    out: dict[str, list[float]] = {}
    for i, name in enumerate(bank.names):
        row = []
        for ax in AXES:
            if ax.key in bank.axis_z:
                z = float(bank.axis_z[ax.key][i])
                pct = (z / spread + 1.0) / 2.0 * 100.0
                row.append(float(np.clip(pct, 0.0, 100.0)))
            else:
                row.append(50.0)
        out[name] = row
    return out


def design_embedding(slider_values: dict[str, float], bank: AnchorBank,
                     top_k: int = 3, allow: set[str] | None = None,
                     **kw) -> tuple[np.ndarray, list[str], np.ndarray]:
    """スライダー → (ブレンド埋め込み(192,), プロンプト用近傍アンカー名, 重み)。

    allow を渡すと、その名前のアンカーだけから選ぶ（例: 感情の合わないアンカーを除く）。
    """
    w = design_weights(slider_values, bank, **kw)
    if allow is not None:
        mask = np.array([n in allow for n in bank.names])
        if mask.any():
            w = np.where(mask, w, 0.0)
            w = w / w.sum()
    if 0 < BLEND_TOP < len(w):   # 上位 BLEND_TOP 人だけ残して正規化
        keep = np.argsort(w)[::-1][:BLEND_TOP]
        sharp = np.zeros_like(w)
        sharp[keep] = w[keep]
        w = sharp / sharp.sum()
    emb = (w[:, None] * bank.embeddings).sum(axis=0)
    order = np.argsort(w)[::-1][:top_k]
    top = [bank.names[i] for i in order]
    return emb.astype(np.float32), top, w
