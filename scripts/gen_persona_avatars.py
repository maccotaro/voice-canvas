"""似ている声のペルソナ用アバター(SVG)を生成する。外部サービスは使わない。

出力: web/public/personas/avatars/<key>.svg（80x80、画面では 40px の丸で表示）
key は web/src/components/canva/SimilarVoices.tsx の PERSONAS と一致させること。

40px でも男女と年代が見分けられるよう、上半身は描かず顔を大きく描く。
女性: 長い髪・まつ毛・色のある口元・丸い輪郭 / 男性: 短い髪・太い眉・角ばったあご
年配: 白髪・目尻と額のしわ

使い方: python scripts/gen_persona_avatars.py
"""
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "web", "public", "personas", "avatars")
INK = "#2a2230"


def face(spec: dict) -> str:
    bg, skin, hair = spec["bg"], spec["skin"], spec["hair"]
    female, old = spec["female"], spec.get("old", False)
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">',
         '<defs><clipPath id="c"><circle cx="40" cy="40" r="40"/></clipPath></defs><g clip-path="url(#c)">',
         f'<rect width="80" height="80" fill="{bg}"/>']

    # 後ろ髪（女性の長い髪・ポニーテール・まとめ髪）
    back = spec.get("back")
    if back == "long":
        p.append(f'<path d="M12 40 Q10 10 40 8 Q70 10 68 40 L70 80 L10 80 Z" fill="{hair}"/>')
    elif back == "pony":
        p.append(f'<path d="M58 22 Q78 26 74 52 Q72 64 64 62 Q72 46 62 32 Z" fill="{hair}"/>')
    elif back == "bun":
        p.append(f'<circle cx="40" cy="9" r="9" fill="{hair}"/>')

    # 首と耳と顔（女性は丸い輪郭、男性は角ばったあご）
    p.append(f'<rect x="31" y="62" width="18" height="20" fill="{skin}"/>')
    p.append(f'<ellipse cx="17" cy="44" rx="4" ry="5.5" fill="{skin}"/><ellipse cx="63" cy="44" rx="4" ry="5.5" fill="{skin}"/>')
    if female:
        p.append(f'<ellipse cx="40" cy="42" rx="22" ry="25" fill="{skin}"/>')
    else:
        p.append(f'<path d="M18 36 Q18 16 40 16 Q62 16 62 36 L62 50 Q60 64 48 68 L32 68 Q20 64 18 50 Z" fill="{skin}"/>')

    # 前髪
    p.append(f'<path d="{spec["front"]}" fill="{hair}"/>')

    # 眉（男性は太く直線的、女性は細く弧）
    bw = 3.0 if not female else 1.8
    brow = spec.get("brow", hair)
    if female:
        p.append(f'<path d="M26 33 Q31 30.5 35 32.5" fill="none" stroke="{brow}" stroke-width="{bw}" stroke-linecap="round"/>'
                 f'<path d="M45 32.5 Q49 30.5 54 33" fill="none" stroke="{brow}" stroke-width="{bw}" stroke-linecap="round"/>')
    else:
        p.append(f'<path d="M25 33 L35 32" stroke="{brow}" stroke-width="{bw}" stroke-linecap="round"/>'
                 f'<path d="M45 32 L55 33" stroke="{brow}" stroke-width="{bw}" stroke-linecap="round"/>')

    # 目
    if spec.get("eyes") == "smile":
        p.append(f'<path d="M26.5 41 Q30.5 37 34.5 41" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round"/>'
                 f'<path d="M45.5 41 Q49.5 37 53.5 41" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round"/>')
    else:
        p.append(f'<ellipse cx="30.5" cy="40" rx="2.6" ry="3" fill="{INK}"/><ellipse cx="49.5" cy="40" rx="2.6" ry="3" fill="{INK}"/>'
                 '<circle cx="31.3" cy="39" r=".9" fill="#fff"/><circle cx="50.3" cy="39" r=".9" fill="#fff"/>')
    if female:   # まつ毛
        p.append(f'<path d="M26.5 38.5 L24.5 36.8 M34.5 38.5 L36 36.6 M45.5 38.5 L44 36.6 M53.5 38.5 L55.5 36.8" '
                 f'stroke="{INK}" stroke-width="1.3" stroke-linecap="round"/>')
    if spec.get("glasses"):
        p.append('<g fill="none" stroke="#1d1a24" stroke-width="1.8"><rect x="23.5" y="34.5" width="14" height="11" rx="3"/>'
                 '<rect x="42.5" y="34.5" width="14" height="11" rx="3"/><path d="M37.5 39 L42.5 39"/></g>')

    # しわ（年配）
    if old:
        p.append('<g fill="none" stroke="#b07e62" stroke-width="1.1" stroke-linecap="round" opacity=".8">'
                 '<path d="M31 25 Q40 23 49 25"/><path d="M33 28 Q40 26.5 47 28"/>'
                 '<path d="M22.5 41.5 L20.5 43"/><path d="M57.5 41.5 L59.5 43"/>'
                 '<path d="M30 55 Q28 52.5 29 50"/><path d="M50 55 Q52 52.5 51 50"/></g>')

    # 頬
    if spec.get("blush"):
        p.append('<ellipse cx="25" cy="50" rx="4" ry="2.6" fill="#ff8fa0" opacity=".5"/>'
                 '<ellipse cx="55" cy="50" rx="4" ry="2.6" fill="#ff8fa0" opacity=".5"/>')

    # 鼻と口
    p.append('<path d="M40 44 Q38.5 49 41 50" fill="none" stroke="#c48a6a" stroke-width="1.4" stroke-linecap="round"/>')
    mouth = spec.get("mouth", "smile")
    lip = "#d9536b" if female else INK
    if mouth == "open":
        p.append('<path d="M33 55 Q40 64 47 55 Z" fill="#8c2f3a"/><path d="M34.6 55.6 L45.4 55.6" stroke="#fff" stroke-width="1.6"/>')
    elif mouth == "calm":
        p.append(f'<path d="M35 57 Q40 59 45 57" fill="none" stroke="{lip}" stroke-width="2" stroke-linecap="round"/>')
    else:
        p.append(f'<path d="M34 56 Q40 61 46 56" fill="none" stroke="{lip}" stroke-width="2.4" stroke-linecap="round"/>')
    if not female and spec.get("stubble"):
        p.append('<path d="M24 56 Q40 74 56 56 L56 62 Q40 76 24 62 Z" fill="#000" opacity=".08"/>')

    p.append("</g></svg>")
    return "".join(p)


PERSONAS = {
    # 40代女性: 肩までの髪、落ち着いた笑み
    "natural_female": dict(bg="#2f6b62", skin="#f1c9a8", hair="#5b3a28", female=True, back="long",
                           front="M18 40 Q16 14 40 13 Q64 14 62 40 Q58 26 46 22 Q36 28 26 26 Q20 30 18 40 Z"),
    # 80代男性: 白髪の短髪、穏やかな口元、しわ
    "calm_male": dict(bg="#3a4868", skin="#e8bf9c", hair="#e4e2dc", female=False, old=True, mouth="calm", brow="#c9c7c0",
                      front="M18 34 Q19 15 40 14 Q61 15 62 34 Q57 23 47 22 Q40 20 33 22 Q23 23 18 34 Z"),
    # 60代男性: 白髪まじりの七三、眼鏡
    "intellectual_male": dict(bg="#473c8a", skin="#edc6a3", hair="#8a8580", female=False, old=True, glasses=True,
                              mouth="calm", brow="#5a554f",
                              front="M18 34 Q17 14 40 13 Q63 14 62 32 Q54 20 36 21 Q26 22 18 34 Z"),
    # 70代女性: 白髪のまとめ髪、目を細めた笑顔、しわ
    "warm_narration": dict(bg="#b5613a", skin="#f0c4a0", hair="#e9e6df", female=True, old=True, back="bun", eyes="smile",
                           brow="#b8b3aa",
                           front="M18 38 Q17 14 40 13 Q63 14 62 38 Q58 22 40 21 Q22 22 18 38 Z"),
    # 30代女性: ポニーテール、前髪、頬、口を開けた笑顔
    "friendly_female": dict(bg="#c24d6c", skin="#f4cfae", hair="#3b2a22", female=True, back="pony", blush=True, mouth="open",
                            eyes="smile",
                            front="M18 36 Q17 13 40 12 Q63 13 62 36 Q56 26 50 25 Q44 29 38 25 Q30 29 24 27 Q20 31 18 36 Z"),
    # 10代男性: 立てた髪、太眉、歯を見せた笑顔
    "energetic_male": dict(bg="#d79418", skin="#e9b98f", hair="#2a1c15", female=False, mouth="open",
                           front="M18 32 L16 16 L25 22 L26 6 L34 18 L40 3 L46 18 L54 6 L55 22 L64 16 L62 32 "
                                 "Q54 22 40 22 Q26 22 18 32 Z"),
}


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for key, spec in PERSONAS.items():
        with open(os.path.join(OUT, f"{key}.svg"), "w", encoding="utf-8") as f:
            f.write(face(spec) + "\n")
        print(f"OK {key}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
