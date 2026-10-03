"""HFの大容量ファイルを curl(停滞検知＋自動再開) で取得し、HFキャッシュへ正しく配置する。

このマシンは hf_hub の大ファイル転送が途中停滞するため（IPv6不通/接続ドロップ）、
curl の --speed-time/--speed-limit で停滞を検知し --retry + -C - で再開しつつ取得する。
blob + snapshots シンボリックリンク + refs/main を hf_hub と同じ構造で作るので、
以後は HF_HUB_OFFLINE=1 でも load_custom_model_from_hf / from_pretrained が参照できる。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from huggingface_hub import hf_hub_url, get_hf_file_metadata
from huggingface_hub.constants import HF_HUB_CACHE


def _meta(url, tries=10):
    last = None
    for _ in range(tries):
        try:
            return get_hf_file_metadata(url)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3)
    raise last


def fetch(repo_id: str, filename: str, cache_dir: str, revision: str = "main") -> str:
    url = hf_hub_url(repo_id, filename, revision=revision)
    m = _meta(url)
    etag = (m.etag or "").strip('"')
    commit = m.commit_hash or revision
    size = m.size
    loc = m.location or url
    base = os.path.join(cache_dir, "models--" + repo_id.replace("/", "--"))
    blobdir = os.path.join(base, "blobs")
    snapdir = os.path.join(base, "snapshots", commit)
    refsdir = os.path.join(base, "refs")
    os.makedirs(blobdir, exist_ok=True)
    os.makedirs(refsdir, exist_ok=True)
    blob = os.path.join(blobdir, etag)
    snap = os.path.join(snapdir, filename)
    os.makedirs(os.path.dirname(snap), exist_ok=True)

    if not (os.path.exists(blob) and (size is None or os.path.getsize(blob) == size)):
        print(f"↓ {repo_id}/{filename}  ({(size or 0)//1024//1024}MB)", flush=True)
        subprocess.run(
            ["curl", "-L", "--fail", "-C", "-",
             "--retry", "50", "--retry-delay", "3", "--retry-all-errors",
             "--speed-time", "20", "--speed-limit", "2000",   # 20秒 2KB/s 未満で切断→再開
             "-o", blob, loc],
            check=True,
        )
    if os.path.islink(snap) or os.path.exists(snap):
        os.remove(snap)
    os.symlink(os.path.relpath(blob, os.path.dirname(snap)), snap)
    with open(os.path.join(refsdir, "main"), "w") as f:
        f.write(commit)
    print(f"OK {repo_id}/{filename} -> {snap} ({os.path.getsize(blob)//1024//1024}MB)", flush=True)
    return snap


def _bigvgan_files(repo_id, tries=10):
    # 推論に必要なのは生成器の重みと設定のみ（discriminator/optimizer等の学習用巨大ファイルは除外）
    return ["bigvgan_generator.pt", "config.json"]


def main() -> int:
    PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ck = os.path.join(PROJ, "external/seed-vc/checkpoints")   # load_custom_model_from_hf のcache
    # ① DiT(44k) と config、② rmvpe → seed-vc/checkpoints
    fetch("Plachta/Seed-VC", "DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth", ck)
    fetch("Plachta/Seed-VC", "config_dit_mel_seed_uvit_whisper_base_f0_44k.yml", ck)
    fetch("lj1995/VoiceConversionWebUI", "rmvpe.pt", ck)
    # ③ bigvgan(44k) → 既定HFキャッシュ(from_pretrainedが参照)
    for fn in _bigvgan_files("nvidia/bigvgan_v2_44khz_128band_512x"):
        if fn.startswith(".") or fn.endswith(".md"):
            continue
        fetch("nvidia/bigvgan_v2_44khz_128band_512x", fn, HF_HUB_CACHE)
    print("ALL_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
