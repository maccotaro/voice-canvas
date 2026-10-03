"""似ている声のサンプル(ペルソナ試聴音声)を生成する。

vocals/source_voice.wav（または data/carrier.wav）をキャリアに、各ペルソナ向けの意味軸スライダー＋高度な調整
(話速/ピッチ揺らぎ/息遣い)で /generate を叩き、web/public/personas/<key>.wav に保存する。
推論サービス(server.py)が http://127.0.0.1:8770 で起動済みであること。
キャリアは Common Voice 日本語の common_voice_ja_39002059.mp3（アンカーとは別話者・CC0）を
無音を詰めて 44.1kHz mono に変換したもの（README「音声素材とライセンス」参照）。

使い方: python scripts/gen_persona_samples.py
"""
import base64
import json
import os
import urllib.request

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJ, "vocals/source_voice.wav")
OUT = os.path.join(PROJ, "web/public/personas")
API = os.environ.get("CANVA_API_URL", "http://127.0.0.1:8770") + "/generate"

# 8軸: age(若い↔年配) gender(男性的↔女性的) pitch(低↔高) build(太↔細)
#       huskiness(クリア↔ハスキー) clarity(こもる↔明瞭) warmth(クール↔ウォーム) roughness(なめらか↔ガラガラ)
# ※ web/src/components/canva/SimilarVoices.tsx の PERSONAS と一致させること。
# DSPは素の生成忠実度を優先し既定オフ（speed=1.0, pitch_variation=0, breathiness=0）。
PERSONAS = [
    ("natural_female", dict(age=40, gender=80, pitch=60, build=60, huskiness=30, clarity=65, warmth=60, roughness=25),
     dict(speed=1.0, pitch_variation=0, breathiness=0)),
    ("calm_male", dict(age=90, gender=10, pitch=15, build=20, huskiness=55, clarity=50, warmth=62, roughness=55),
     dict(speed=1.0, pitch_variation=0, breathiness=0)),
    ("intellectual_male", dict(age=60, gender=12, pitch=30, build=45, huskiness=15, clarity=88, warmth=30, roughness=12),
     dict(speed=1.0, pitch_variation=0, breathiness=0)),
    ("warm_narration", dict(age=70, gender=80, pitch=45, build=40, huskiness=35, clarity=60, warmth=92, roughness=30),
     dict(speed=1.0, pitch_variation=0, breathiness=0)),
    ("friendly_female", dict(age=30, gender=85, pitch=55, build=60, huskiness=20, clarity=72, warmth=85, roughness=15),
     dict(speed=1.0, pitch_variation=0, breathiness=0)),
    ("energetic_male", dict(age=15, gender=10, pitch=45, build=55, huskiness=30, clarity=80, warmth=45, roughness=60),
     dict(speed=1.0, pitch_variation=0, breathiness=0)),
]


# サンプルに使うアンカーの絞り込み。サンプルは「その性別の声」で「明るい・落ち着いた」印象にしたいので、
# 反対の性別のアンカーと、明るくない感情（JVNV の悲しみ・恐れ・嫌悪・怒り）のアンカーは使わない。
# 性別は key の _female / _male で決める（web 側 PERSONAS の gender と一致）。
EXCLUDE_EMOTIONS = ("_sad", "_fear", "_disgust", "_anger")


def allowed_anchors(sex: str) -> list[str]:
    """推論サービスのアンカー一覧（素材ラベル付き）から、サンプルに使ってよいアンカー名を返す。"""
    base = API.rsplit("/", 1)[0]
    items = json.load(urllib.request.urlopen(f"{base}/anchors/admin", timeout=60))["anchors"]
    want = "女性" if sex == "female" else "男性"
    return [a["name"] for a in items
            if a["source"].startswith(want) and not any(e in a["name"] for e in EXCLUDE_EMOTIONS)]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    carrier = "data:audio/wav;base64," + base64.b64encode(open(SRC, "rb").read()).decode()
    for key, sliders, adv in PERSONAS:
        sex = "female" if key.endswith("_female") or key == "warm_narration" else "male"
        body = json.dumps(dict(sliders=sliders, carrier_b64=carrier, anchors=allowed_anchors(sex), **adv)).encode()
        req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=300))
        wav = base64.b64decode(r["wav_b64"].split(",")[-1])
        with open(os.path.join(OUT, f"{key}.wav"), "wb") as f:
            f.write(wav)
        top = ", ".join(f"{t['name']}({t['weight'] * 100:.0f}%)" for t in r.get("top", [])[:3])
        print(f"OK {key} -> {len(wav) // 1024}KB  近いアンカー: {top}", flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
