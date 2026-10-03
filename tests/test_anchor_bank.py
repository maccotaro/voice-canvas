"""アンカー管理まわりの単体検証（Seed-VC やモデルを読み込まずに確かめられる範囲）。

検証内容:
- 埋め込みファイルが無いとき、load_bank が空のバンクを返す（初回セットアップ前でも起動できる）。
- add_anchor / remove_anchor でバンクが増減し、最後の1件を外すと空のバンクに戻る。
- cut_windows が 4s と 12s を切り出し、ピークを 0.9 に揃える。
- select_best は窓を取れないほど短い素材を (None, False) で返す。
"""
from __future__ import annotations

import numpy as np

from voice_canva import anchor_select as sel
from voice_canva import design


def _attr(f0: float, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    return dict(f0_mean=f0, hnr=10.0 + rng.normal(), spectral_tilt=-10.0 + rng.normal(),
                shimmer=0.05 + 0.01 * rng.random(), jitter=0.01 + 0.002 * rng.random(),
                formants=np.array([500.0, 1500.0, 2500.0, 3500.0]) * (1 + 0.05 * rng.normal()))


def test_load_bank_without_embeddings_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "_EMB", str(tmp_path / "missing.npz"))
    bank = design.load_bank()
    assert bank.names == [] and bank.embeddings.shape == (0, 192)
    assert design.anchor_slider_values(bank) == {}


def test_add_and_remove_anchor_rebuilds_bank():
    bank = design.empty_bank()
    for i, f0 in enumerate([110.0, 180.0, 240.0]):
        bank = design.add_anchor(bank, f"spk{i + 1}", np.full(192, float(i)), _attr(f0, i))
    assert bank.names == ["spk1", "spk2", "spk3"]
    assert len(bank.names) >= design.MIN_ANCHORS
    # 声の高さの軸で、低い声は高い声より低い位置になる
    sv = design.anchor_slider_values(bank)
    pitch = design.AXIS_KEYS.index("pitch")
    assert sv["spk1"][pitch] < sv["spk3"][pitch]

    bank = design.remove_anchor(bank, "spk2")
    assert bank.names == ["spk1", "spk3"]
    assert np.allclose(bank.embeddings[:, 0], [0.0, 2.0])
    bank = design.remove_anchor(design.remove_anchor(bank, "spk1"), "spk3")
    assert bank.names == [] and bank.embeddings.shape == (0, 192)


def test_cut_windows_lengths_and_peak():
    sr = 16000
    y = np.sin(np.linspace(0, 2000 * np.pi, sr * 30)).astype(np.float32) * 0.3
    seg4, seg12 = sel.cut_windows(y, sr, center_s=10.0)
    assert len(seg4) == 4 * sr and len(seg12) == 12 * sr
    assert abs(float(np.max(np.abs(seg4))) - 0.9) < 1e-3


def test_select_best_rejects_too_short_audio():
    y16 = np.zeros(int(sel.SR16 * (sel.MIN_SEC - 2)), np.float32)
    best, passed = sel.select_best(lambda seg: np.zeros(192), y16)
    assert best is None and passed is False


def test_default_pack_installs_once_and_attrs_roundtrip(tmp_path, monkeypatch):
    """同梱パックは初回だけ展開され、音響スカラは JSON 経由で復元できる。"""
    import json

    import soundfile as sf

    from voice_canva import default_anchors

    pack = tmp_path / "anchors" / "default"
    (pack / "audio").mkdir(parents=True)
    sr = 16000
    anchors = []
    for i in range(3):
        sf.write(pack / "audio" / f"spk{i + 1}.flac", np.random.default_rng(i).normal(0, 0.1, sr * 12), sr)
        a = _attr(120.0 + 60 * i, i)
        anchors.append({"name": f"spk{i + 1}", "label": "テスト", "f0": a["f0_mean"],
                        "attrs": design.attrs_to_json(a)})
    sf.write(pack / "carrier.flac", np.zeros(sr * 3), sr)
    (pack / "manifest.json").write_text(json.dumps({"anchors": anchors, "carrier": "carrier.flac"}), encoding="utf-8")
    np.savez(pack / "embeddings.npz", names=np.array(["spk1", "spk2", "spk3"]), embeddings=np.eye(3, 192))

    monkeypatch.setattr(design, "_EMB", str(tmp_path / "data" / "anchor_embeddings.npz"))
    monkeypatch.setattr(design, "_ATTRS", str(tmp_path / "data" / "anchor_attrs.json"))
    assert default_anchors.install(str(tmp_path)) == 3
    assert default_anchors.install(str(tmp_path)) == 0            # 2 回目は何もしない
    data = tmp_path / "data"
    assert (data / "carrier.wav").exists() and (data / "spk2.wav").exists()
    assert len(sf.read(data / "spk2.wav")[0]) == 4 * sr           # 12 秒から 4 秒を切り出す
    assert not (tmp_path / "features").exists()                   # 再合成できる配列は作らない
    bank = design.load_bank()
    assert bank.names == ["spk1", "spk2", "spk3"]
    assert abs(bank.attrs[2]["f0_mean"] - anchors[2]["attrs"]["f0_mean"]) < 1e-9


def test_design_embedding_blends_only_top_anchors():
    """混ぜるのは重みの大きい BLEND_TOP 人だけ（全員を薄く混ぜて平均的な声になるのを防ぐ）。"""
    bank = design.empty_bank()
    for i, f0 in enumerate(np.linspace(90, 260, 10)):
        bank = design.add_anchor(bank, f"spk{i + 1}", np.eye(192)[i], _attr(float(f0), i))
    emb, top, w = design.design_embedding({"pitch": 0.9, "gender": 0.9}, bank)
    assert int((w > 0).sum()) == design.BLEND_TOP
    assert abs(float(w.sum()) - 1.0) < 1e-9
    assert set(top) <= {bank.names[i] for i in np.flatnonzero(w)}
    # 埋め込みは選ばれたアンカーだけの重み付き和
    assert np.allclose(emb[:10], w[:10], atol=1e-6)


def test_default_pack_adds_only_new_anchors(tmp_path, monkeypatch):
    """展開済みの環境では、パックに増えたアンカーだけを足す。外したアンカーは戻さない。"""
    import json

    import soundfile as sf

    from voice_canva import default_anchors

    pack = tmp_path / "anchors" / "default"
    (pack / "audio").mkdir(parents=True)
    sr = 16000
    names = ["spk1", "spk2", "jvnv_f1_happy", "jvnv_m1_sad"]

    def write_pack(ns):
        anchors = []
        for i, n in enumerate(ns):
            sf.write(pack / "audio" / f"{n}.flac", np.random.default_rng(i).normal(0, 0.1, sr * 12), sr)
            anchors.append({"name": n, "label": n, "f0": 150.0, "attrs": design.attrs_to_json(_attr(100.0 + 40 * i, i))})
        (pack / "manifest.json").write_text(json.dumps({"anchors": anchors}), encoding="utf-8")
        np.savez(pack / "embeddings.npz", names=np.array(ns), embeddings=np.eye(len(ns), 192) * (np.arange(len(ns)) + 1)[:, None])

    monkeypatch.setattr(design, "_EMB", str(tmp_path / "data" / "anchor_embeddings.npz"))
    monkeypatch.setattr(design, "_ATTRS", str(tmp_path / "data" / "anchor_attrs.json"))
    write_pack(names[:2])
    assert default_anchors.install(str(tmp_path)) == 2
    # 利用者が spk2 を外した（_excluded へ退避）
    ex = tmp_path / "data" / "_excluded"
    ex.mkdir()
    (tmp_path / "data" / "tgt_spk2_long.wav").rename(ex / "tgt_spk2_long.wav")
    d = np.load(tmp_path / "data" / "anchor_embeddings.npz")
    np.savez(tmp_path / "data" / "anchor_embeddings.npz", names=d["names"][:1], embeddings=d["embeddings"][:1])

    write_pack(names)   # パックが 4 人に増えた
    assert default_anchors.install(str(tmp_path)) == 2            # jvnv の 2 人だけ追加
    bank = design.load_bank()
    assert bank.names == ["spk1", "jvnv_f1_happy", "jvnv_m1_sad"]  # spk2（外した）は戻らない
    assert np.allclose(bank.embeddings[0, 0], 1.0)                  # 既存の埋め込みは保持
    assert default_anchors.install(str(tmp_path)) == 0


def test_age_axis_uses_real_age_labels():
    """年齢感は実年代のラベルで決まる（声の低さではない）。ラベルの無いアンカーは中立。"""
    bank = design.empty_bank()
    # 高い声の年配と、低い声の若者（声の低さ＝年配、という近似だと逆に選ばれる組み合わせ）
    for i, (f0, age) in enumerate([(240, 70), (230, 65), (225, 68), (100, 18), (105, 22), (110, 20), (160, None)]):
        a = _attr(float(f0), i)
        if age is not None:
            a["age"] = float(age)
        bank = design.add_anchor(bank, f"a{i}", np.eye(192)[i], a)
    old = design.anchor_slider_values(bank)
    k = design.AXIS_KEYS.index("age")
    assert old["a0"][k] > old["a3"][k]            # 高い声でも年配は「年配」側
    assert abs(old["a6"][k] - 50.0) < 15.0         # 年齢不明は中立付近
    _, _, w = design.design_embedding({"age": 1.0}, bank)
    top = bank.names[int(np.argmax(w))]
    assert top in ("a0", "a1", "a2")


def test_design_embedding_can_restrict_anchors():
    bank = design.empty_bank()
    for i, f0 in enumerate(np.linspace(90, 260, 8)):
        bank = design.add_anchor(bank, f"jvnv_f1_{'sad' if i % 2 else 'happy'}{i}", np.eye(192)[i], _attr(float(f0), i))
    allow = {n for n in bank.names if "sad" not in n}
    _, _, w = design.design_embedding({"pitch": 0.9}, bank, allow=allow)
    assert all(bank.names[j] in allow for j in np.flatnonzero(w))


def test_bundled_names_and_remove_attrs(tmp_path, monkeypatch):
    """同梱パックの名前が取れる（削除を断る根拠）。完全削除で素属性の記録も消える。"""
    from pathlib import Path
    from voice_canva import default_anchors
    repo = Path(__file__).resolve().parents[1]
    names = default_anchors.bundled_names(str(repo))
    assert "spk1" in names and len(names) >= design.MIN_ANCHORS
    assert default_anchors.bundled_names(str(tmp_path)) == set()   # パックが無ければ空

    monkeypatch.setattr(design, "_ATTRS", str(tmp_path / "anchor_attrs.json"))
    design.write_attrs({"spk40": _attr(150.0, 1), "spk41": _attr(200.0, 2)})
    design.remove_attrs(["spk40", "missing"])
    assert set(design.read_attrs()) == {"spk41"}
