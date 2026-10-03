# 実装コントラクト（全モジュール厳守）

`voice_canva/config.py` が定数・軸定義の Single Source of Truth。各モジュールはこれを import する。
ハードコードや独自定数の重複定義は禁止（CLAUDE.md 開発原則）。

## データ型（`voice_canva/analysis.py` が定義）

```python
@dataclass
class SpeakerFeatures:
    name: str                 # 話者ID
    sr: int                   # サンプルレート (= config.DEFAULT_SR)
    frame_period: float       # = config.FRAME_PERIOD
    f0: np.ndarray            # (T,)  フレーム単位 F0 [Hz]
    sp: np.ndarray            # (T, F) スペクトル包絡 (pyworld cheaptrick)
    ap: np.ndarray            # (T, F) 非周期性 (pyworld d4c)
    # parselmouth 由来のスカラ統計（軸マッピングの相関分析・±2σに使う）
    f0_mean: float
    f0_std: float             # F0 安定性の逆指標
    formants: np.ndarray      # (4,) F1..F4 平均 [Hz]
    jitter: float
    shimmer: float
    hnr: float                # Harmonics-to-Noise Ratio [dB]
    spectral_tilt: float      # スペクトル傾斜 [dB/oct]

    def save(self, path: str) -> None        # npz で保存（配列）+ 同名 .json（スカラ）
    @classmethod
    def load(cls, path: str) -> "SpeakerFeatures"
```

## 関数シグネチャ（厳守）

### analysis.py
```python
def analyze_wav(path: str, name: str | None = None, sr: int = config.DEFAULT_SR) -> SpeakerFeatures
def analyze_dir(data_dir: str = config.PATHS.data_dir, out_dir: str = config.PATHS.features_dir) -> list[SpeakerFeatures]
```
- pyworld: harvest→F0, stonemask 精緻化, cheaptrick→SP, d4c→AP。
- parselmouth: formants(Burg), jitter(local), shimmer(local), HNR, spectral tilt。
- 音声は librosa で `sr` にリサンプル・モノラル化してから処理。

### axes.py
```python
@dataclass
class AxisRanges:           # 各軸の物理可動域（±2σ ベース）
    per_axis: dict[str, tuple[float, float]]   # axis_key -> (min, max) 正規化外の参考値
def compute_ranges(features: list[SpeakerFeatures]) -> AxisRanges
def default_axis_values() -> dict[str, float]   # 全軸 0.0（= ベース話者そのまま）

# 軸値(正規化 -1..+1) と ベース話者特徴 → 変更後の WORLD パラメータ
def apply_axes(axis_values: dict[str, float], base: SpeakerFeatures,
               ranges: AxisRanges | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """return (f0_mod, sp_mod, ap_mod) — pyworld.synthesize にそのまま渡せる形。"""
```
- 変換は config.GAINS と AxisRanges を反映した線形（区分線形可）。
- F0 は半音スケーリング、フォルマントは SP の周波数軸ワーピング、明るさは SP のスペクトル傾斜、
  気息は AP のスケーリングで実現。**生パラメータを独立に動かさず相関連動させる**（memo §2.1）。

### synthesis.py
```python
def synthesize(axis_values: dict[str, float], base: SpeakerFeatures,
               ranges: "AxisRanges | None" = None) -> np.ndarray:
    """axes.apply_axes → pyworld.synthesize。戻り値は float32 mono 波形 (T,)。"""
```
- 1 文あたり数百 ms〜秒で返ること（即試聴ループ用）。

### io_utils.py
```python
def load_wav(path: str, sr: int = config.DEFAULT_SR) -> tuple[np.ndarray, int]
def save_wav(path: str, wav: np.ndarray, sr: int) -> None
def export_reference(wav: np.ndarray, sr: int,
                     out_dir: str = config.PATHS.output_dir,
                     name: str = config.PATHS.reference_name) -> str   # 書き出しパスを返す
```

### app.py（Gradio）
```python
def build_demo(base: SpeakerFeatures, ranges: AxisRanges) -> "gr.Blocks"
def main() -> None   # features_dir から最初の話者を読み込み build_demo→launch
```
- 6 本スライダー：ラベルは `config.AXES` の label/low/high、レンジは `config.AXIS_MIN..AXIS_MAX`。
- 「再生」: 現在値で synthesize→ その場で試聴（gr.Audio）。スライダー変更で即時プレビュー。
- 「reference.wav として書き出し」ボタン → io_utils.export_reference。

## scripts/step0_analysis_resynth.py
memo Step 0 の単体検証スクリプト。引数 wav を pyworld で分析→そのまま再合成して保存し、
さらに F0 を ±2 半音スケーリングした版も書き出す（破綻しないことの耳確認用）。

## 規約
- Python 3.10+, 型ヒント必須, `from __future__ import annotations`。
- 依存が無い環境でも import 時に即クラッシュしないよう、重い依存（pyworld 等）は関数内 import 可。
- docstring は日本語。memo.md の設計思想（§2.1〜2.3, §5）を逸脱しない。
