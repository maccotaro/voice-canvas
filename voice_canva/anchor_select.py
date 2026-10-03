"""話者録音からアンカーにする区間を選ぶ（CLI の seedvc/select_anchors.py と推論サービスで共用）。

2 段階で選ぶ:
  Stage1 (pyin/RMS) — 4s 窓ごとに「落ち着き＋安定性」を評価（抑揚過多・声量変動・ホールド音・
                       常用音域からの乖離を減点）
  Stage2 (話者埋め込み) — 上位候補の 12s 範囲を 3s チャンクに分け、2 クラスタの重心コサインで
                       単一話者性を判定（話者交代があると低い）
最後に録音品質(SQUIM の PESQ 推定)を見て、単一話者かつ品質を満たす中で最も自然な窓を採る。

話者埋め込みは呼び出し側が `embed_fn(seg16: np.ndarray) -> np.ndarray` として渡す
（Seed-VC の campplus を、CLI とサービスがそれぞれのデバイスで動かすため）。
"""
from __future__ import annotations

from typing import Callable

import librosa
import numpy as np

SR16 = 16000
WIN_S = 4.0          # stage1 分析窓（4s 切り出しと一致）
EXT_S = 12.0         # 12s 切り出し範囲（単一話者判定もこの範囲で行う）
GUARD_S = 5.0        # ファイル端のガード
N_CAND = 48          # stage1 等間隔候補数
TOP_K = 16           # stage2 にかける上位候補数
CHUNK_S = 3.0        # 単一話者判定のチャンク長
CHUNK_HOP_S = 1.5    # チャンクのホップ（重なりで埋め込みを安定化）

HOMO_THRESH = 0.55   # 単一話者の最小コサイン（既定）
PESQ_THRESH = 2.3    # 録音品質(SQUIM PESQ 推定)の最小値（既定）
MIN_SEC = 2 * GUARD_S + WIN_S + 1.0   # これより短い素材は窓を取れない（コーパスから選ぶとき）

# 画面からの追加（その場の録音など）は気軽に試せるよう、止めるのは「短すぎる」「話し声が無い」だけにする。
# 単一話者・録音品質は基準を下回っても採用し、注意として見せる（使うかどうかは利用者が決める）
LIGHT_MIN_SEC = 8.0
LIGHT_GUARD_S = 0.5  # 録音の頭と終わりの端（マイクの立ち上がり・止める操作の音）だけ避ける

# 発声の自然さ ペナルティ重み（自然さが生の確度/安定性に勝つよう強めに設定）
SPREAD_TARGET = 6.0  # 自然な会話の抑揚[半音]の目安。ここから外れるほど減点
W_SPREAD = 0.12   # |抑揚 - 目標|[半音]（高=感情過多 / 低=棒読み・単調）
W_ECV = 0.5       # エネルギー変動係数（大=声量変動=感情的）
W_HOLD = 1.2      # 0.5s 超のホールド音[s]（持続発声/歌唱/伸ばし）
W_MODAL = 0.25    # 話者常用音域からの F0 乖離[半音]（裏声/叫び/キャラ声）
HOLD_FREE_S = 0.5  # この長さまでのホールドは自然発声として許容

EmbedFn = Callable[[np.ndarray], np.ndarray]


# ---------------- Stage1: 発声の自然さ＋安定性 ----------------
def stage1_feats(seg16: np.ndarray) -> dict | None:
    """4s 窓の生の発声指標を返す（複合スコアは modal 確定後に composite で計算）。"""
    f0, _vflag, vprob = librosa.pyin(seg16, fmin=70, fmax=500, sr=SR16,
                                     frame_length=1024, hop_length=256)
    voiced = ~np.isnan(f0)
    vr = float(np.mean(voiced))
    if vr < 0.4 or vr > 0.92:                 # 無声過多 or 連続母音すぎ
        return None
    fv = f0[voiced]
    if len(fv) < 10:
        return None
    lf = np.log2(fv)
    instab = float(np.median(np.abs(np.diff(lf))) * 12.0)             # 微小安定性[半音]
    spread = float((np.percentile(lf, 90) - np.percentile(lf, 10)) * 12.0)  # 抑揚幅[半音]
    conf = float(np.nanmean(vprob[voiced]))
    f0med = float(np.median(fv))
    rms = librosa.feature.rms(y=seg16, frame_length=1024, hop_length=256)[0]
    ecv = float(np.std(rms) / (np.mean(rms) + 1e-9))                  # 声量変動係数
    # 最長ホールド音[s]: 連続有声で隣接 F0 が ±0.5 半音以内に留まる最大長
    semi = np.abs(np.diff(np.log2(f0))) * 12.0
    hop_s = 256.0 / SR16
    run = mx = 0
    for s in semi:
        if (not np.isnan(s)) and s < 0.5:
            run += 1
            mx = max(mx, run)
        else:
            run = 0
    hold = mx * hop_s
    return dict(instab=instab, spread=spread, conf=conf, vr=vr, f0=f0med, ecv=ecv, hold=hold)


def composite(c: dict, modal_f0: float) -> float:
    """生指標 + 話者常用音域(modal_f0) から最終スコア（高=自然で落ち着いた発声）。

    抑揚はバンド評価（目標 SPREAD_TARGET から外れるほど減点。感情過多も棒読みも回避）。
    ホールド音・常用音域からの乖離（裏声/叫び/歌唱）を強く減点し、自然な発声を優先する。
    """
    modal_dev = abs(np.log2(max(c["f0"], 1e-6) / max(modal_f0, 1e-6))) * 12.0  # [半音]
    pen = (W_SPREAD * abs(c["spread"] - SPREAD_TARGET)
           + W_ECV * c["ecv"]
           + W_HOLD * max(0.0, c["hold"] - HOLD_FREE_S)
           + W_MODAL * modal_dev)
    base = c["conf"] / (1.0 + c["instab"])
    return base / (1.0 + pen)


# ---------------- Stage2: 単一話者性 ----------------
def homogeneity(embed_fn: EmbedFn, y16: np.ndarray, center_s: float) -> float | None:
    """12s 切り出し範囲を重複チャンク化し「単一話者スコア」を返す（高=単一話者）。

    各チャンクの話者埋め込みを 2 クラスタに分割（最も非類似なチャンク対を種に最近傍割当）し、
    2 重心間のコサインを返す。単一話者なら音素差による軽微な分散のみで重心が近く高い値、
    話者交代があれば重心が離れて低い値になる（2 話者検定）。
    """
    s = max(0.0, center_s - 4.0)
    i0 = int(s * SR16)
    i1 = min(len(y16), i0 + int(EXT_S * SR16))
    region = y16[i0:i1]
    win = int(CHUNK_S * SR16)
    hop = int(CHUNK_HOP_S * SR16)
    embs = []
    for j in range(0, len(region) - win + 1, hop):
        ch = region[j:j + win]
        if float(np.max(np.abs(ch))) < 1e-3:
            continue
        embs.append(embed_fn(ch))
    if len(embs) < 4:
        return None
    E = np.stack(embs)
    E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
    S = E @ E.T
    a, b = np.unravel_index(int(np.argmin(S)), S.shape)
    assign = (S[a] < S[b]).astype(int)          # 0=種a寄り, 1=種b寄り
    if assign.min() == assign.max():            # 片寄り（実質単一クラスタ）
        return 1.0
    c0 = E[assign == 0].mean(axis=0)
    c1 = E[assign == 1].mean(axis=0)
    c0 /= np.linalg.norm(c0) + 1e-9
    c1 /= np.linalg.norm(c1) + 1e-9
    return float(np.dot(c0, c1))


def pesq(squim, y16: np.ndarray, center_s: float) -> float:
    """12s 切り出し範囲の無参照品質(PESQ推定, SQUIM)。録音のクリーンさの指標。"""
    if squim is None:
        return 0.0
    import torch

    s = max(0.0, center_s - 4.0)
    i0 = int(s * SR16)
    seg = y16[i0:i0 + int(EXT_S * SR16)]
    if len(seg) < SR16:
        return 0.0
    with torch.inference_mode():
        _stoi, p, _sisdr = squim(torch.tensor(seg).unsqueeze(0).float())
    return float(p.item())


def select_best(embed_fn: EmbedFn, y16: np.ndarray, homo_thresh: float = HOMO_THRESH,
                squim=None, pesq_thresh: float = 0.0, on_progress: Callable[[str], None] | None = None,
                guard_s: float = GUARD_S, unknown_ok: bool = False):
    """1 ファイルから最良窓を選ぶ。戻り値 (best_dict | None, passed_bool)。

    単一話者(homog>=homo_thresh)かつ品質(pesq>=pesq_thresh)を満たす候補から、最も自然な窓を採用。
    満たすものが無ければ順に条件を緩める（passed=False で返す）。
    guard_s はファイル端の避ける長さ。unknown_ok=True なら、短くて単一話者を判定できない窓
    （homog=None）も通す（判定できなかったことは呼び出し側が注意として出す）。
    """
    win = int(WIN_S * SR16)
    guard = int(guard_s * SR16)
    hi = len(y16) - guard - win
    if hi <= guard:
        return None, False

    if on_progress:
        on_progress("落ち着いた区間を探しています")
    cands = []
    for p in np.linspace(guard, hi, N_CAND).astype(int):
        seg = y16[p:p + win]
        if float(np.max(np.abs(seg))) < 1e-3:
            continue
        m = stage1_feats(seg)
        if m is None:
            continue
        cands.append({**m, "pos16": int(p), "center": p / SR16})
    if not cands:
        return None, False

    modal_f0 = float(np.median([c["f0"] for c in cands]))
    for c in cands:
        c["modal_dev"] = abs(np.log2(max(c["f0"], 1e-6) / max(modal_f0, 1e-6))) * 12.0
        c["score"] = composite(c, modal_f0)

    cands.sort(key=lambda c: -c["score"])
    topk = cands[:TOP_K]
    if on_progress:
        on_progress("話者が1人かを確かめています")
    for c in topk:
        h = homogeneity(embed_fn, y16, c["center"])
        c["homog"] = (None if unknown_ok else -1.0) if h is None else h

    passed = [c for c in topk if c["homog"] is None or c["homog"] >= homo_thresh]
    pool = passed if passed else topk
    if on_progress and squim is not None:
        on_progress("録音品質を測っています")
    for c in pool:
        c["pesq"] = pesq(squim, y16, c["center"])
    good = [c for c in pool if c["pesq"] >= pesq_thresh]
    if passed and good:
        best = max(good, key=lambda c: c["score"])
    elif passed:
        best = max(pool, key=lambda c: c["pesq"])       # 単一話者だが品質未達→最良品質
    else:
        best = max(pool, key=lambda c: c["homog"] if c["homog"] is not None else 0.0)  # 妥協: 最も単一話者寄り
        best.setdefault("pesq", pesq(squim, y16, best["center"]))
    return best, bool(passed and good)


def cut_windows(y: np.ndarray, sr: int, center_s: float) -> tuple[np.ndarray, np.ndarray]:
    """選んだ窓から 4s（分析・試聴用）と 12s（VC ターゲット用）を切り出して正規化する。"""
    out = []
    for ws in (4.0, 12.0):
        start = max(0.0, center_s + 2.0 - ws / 2.0)
        i = int(start * sr)
        seg = y[i:i + int(ws * sr)]
        out.append((seg / (np.max(np.abs(seg)) + 1e-9) * 0.9).astype("float32"))
    return out[0], out[1]
