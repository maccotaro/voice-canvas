"""安定基準で1話者を抽出: add_speaker.py <wav> <name>"""
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, soundfile as sf, librosa
sys.path.insert(0, "scripts")
from extract_stable import _score_window, SR16

F, name = sys.argv[1], sys.argv[2]
y, sr = sf.read(F, dtype="float32")
if y.ndim > 1: y = y.mean(1)
y16 = librosa.resample(y, orig_sr=sr, target_sr=SR16)
win, guard = int(4.0*SR16), int(5*SR16)
best = None
for p in np.linspace(guard, len(y16)-guard-win, 40).astype(int):
    seg = y16[p:p+win]
    if float(np.max(np.abs(seg))) < 1e-3: continue
    m = _score_window(seg)
    if m and (best is None or m["score"] > best["score"]): best = {**m, "pos16": p}
if best is None:
    print(f"{name}: 安定候補なし"); sys.exit(1)
center = best["pos16"]/SR16
for ws, out in [(4.0, f"data/{name}.wav"), (12.0, f"data/tgt_{name}_long.wav")]:
    i = int(max(0.0, center+2.0-ws/2.0)*sr); seg = y[i:i+int(ws*sr)]
    seg = seg/(np.max(np.abs(seg))+1e-9)*0.9
    sf.write(out, seg.astype("float32"), sr, subtype="PCM_16")
print(f"{name}: @{center:.0f}s 不安定={best['instab']:.2f}半音 確度={best['conf']:.2f} 有声={best['vr']:.2f} F0={best['f0']:.0f}Hz dur={len(y)/sr:.0f}s")
