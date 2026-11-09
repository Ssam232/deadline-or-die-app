"""
🎨 Car art — original, stylized side profiles by body style. Every upgrade is visible on the car.

Front of the car faces right. Pure functions returning SVG strings.
"""
from __future__ import annotations

import html
import math

GROUND = 124
R_TIRE = 19

# Upper body profile (rear-bottom → over the top → front-bottom), glass, light positions, wheel x's.
BODIES = {
    "sedan": {
        "top": "M18,104 L18,88 Q18,78 30,76 L66,72 Q78,70 92,58 L112,44 Q126,37 150,36 L198,36 Q214,37 228,48 "
               "L250,64 L300,68 Q330,71 338,80 Q342,88 340,104",
        "glass": "M98,60 L114,47 Q128,40 150,40 L196,40 Q210,41 222,51 L236,62 Z",
        "pillar": 158, "head": (322, 72, 14, 6), "tail": (19, 79, 8, 9), "wheels": (84, 272),
        "deck": (30, 74), "roof_y": 36, "hood": (250, 300, 66), "door": (110, 236), "roundel": (176, 88),
    },
    "coupe": {
        "top": "M18,104 L18,90 Q18,80 30,78 L56,76 Q74,72 96,54 L118,42 Q136,36 160,36 L196,37 Q212,39 226,50 "
               "L248,64 L302,69 Q330,72 338,82 Q342,90 340,104",
        "glass": "M102,57 L121,45 Q137,40 160,40 L194,41 Q208,43 219,52 L232,62 Z",
        "pillar": None, "head": (322, 74, 14, 6), "tail": (19, 82, 8, 8), "wheels": (84, 272),
        "deck": (32, 76), "roof_y": 36, "hood": (248, 302, 67), "door": (128, 236), "roundel": (180, 88),
    },
    "roadster": {
        "top": "M18,104 L18,86 Q20,76 34,75 L100,73 Q108,72 114,68 L192,68 L202,66 L304,70 Q332,73 338,82 "
               "Q342,90 340,104",
        "glass": "M176,47 L181,47 L203,66 L197,66 Z",
        "pillar": None, "head": (322, 73, 14, 6), "tail": (19, 80, 8, 8), "wheels": (84, 272),
        "deck": (34, 74), "roof_y": 60, "hood": (205, 304, 68), "door": (130, 226), "roundel": (170, 88),
        "roadster": True,
    },
    "hatch": {
        "top": "M20,104 L20,74 Q22,58 34,52 L62,42 Q76,36 98,35 L190,35 Q210,36 226,48 L250,64 L300,68 "
               "Q330,71 338,80 Q342,88 340,104",
        "glass": "M70,62 L66,47 Q80,40 98,39 L188,39 Q206,40 220,50 L234,62 Z",
        "pillar": 150, "head": (322, 72, 14, 6), "tail": (21, 70, 7, 12), "wheels": (84, 272),
        "deck": (30, 66), "roof_y": 35, "hood": (250, 300, 66), "door": (104, 234), "roundel": (172, 88),
    },
    "super": {
        "top": "M14,104 L14,92 Q14,84 26,82 L92,78 Q108,76 128,66 L146,57 Q160,51 180,50 L204,51 Q222,53 236,64 "
               "L256,76 L310,82 Q336,86 342,94 Q345,99 343,104",
        "glass": "M134,70 L150,60 Q162,55 180,54 L203,55 Q218,57 230,66 L236,73 Z",
        "pillar": None, "head": (326, 86, 13, 4), "tail": (15, 85, 10, 5), "wheels": (90, 272),
        "deck": (40, 80), "roof_y": 50, "hood": (256, 310, 78), "door": (150, 240), "roundel": (194, 96),
        "intake": "M112,90 L146,86 L144,100 L116,101 Z",
    },
}
BODIES["super2"] = {
    "top": "M14,104 L14,90 Q15,82 28,80 L96,76 Q112,74 130,63 L150,53 Q164,48 184,48 L206,49 Q226,52 240,64 "
           "L262,78 L314,83 Q338,86 344,95 Q346,100 344,104",
    "glass": "M138,66 L154,57 Q166,52 184,52 L205,53 Q222,56 234,66 L240,73 Z",
    "pillar": None, "head": (328, 84, 13, 3), "tail": (15, 83, 11, 4), "wheels": (90, 274),
    "deck": (40, 78), "roof_y": 48, "hood": (262, 314, 80), "door": (152, 242), "roundel": (196, 96),
    "intake": "M108,88 L150,82 L148,101 L112,101 Z",
}
BODIES["gt3"] = {**BODIES["super2"], "gt3": True}
# ── the Acura ladder: stylized, original silhouettes in the same language (no badges, no replicas) ──
BODIES["rsx"] = {  # compact three-door liftback coupe: short wheelbase, glass sloping all the way to the tail
    "top": "M20,104 L20,82 Q21,73 32,70 L56,63 Q78,54 100,45 L120,38 Q134,35 152,35 L190,36 Q206,38 220,48 "
           "L244,63 L296,68 Q326,71 335,80 Q339,88 338,104",
    "glass": "M64,63 L100,47 Q122,39 152,39 L188,40 Q202,42 214,51 L228,61 Z",
    "pillar": 146, "head": (320, 72, 14, 6), "tail": (21, 72, 8, 8), "wheels": (92, 266),
    "deck": (38, 66), "roof_y": 35, "hood": (244, 296, 65), "door": (112, 228), "roundel": (174, 88),
}
BODIES["tsx"] = {  # tidy four-door sport sedan
    "top": "M18,104 L18,87 Q18,78 30,76 L70,72 Q84,69 98,57 L116,44 Q130,37 152,36 L196,36 Q212,37 226,48 "
           "L248,63 L302,67 Q331,70 339,80 Q343,88 341,104",
    "glass": "M104,59 L119,47 Q132,41 152,40 L194,40 Q208,41 220,51 L234,62 Z",
    "pillar": 160, "head": (323, 71, 14, 6), "tail": (19, 78, 8, 9), "wheels": (84, 272),
    "deck": (32, 74), "roof_y": 36, "hood": (248, 302, 65), "door": (112, 236), "roundel": (178, 88),
}
BODIES["integra_s"] = {  # five-door liftback with a fastback roofline and flared arches
    "top": "M16,104 L16,84 Q17,74 28,71 L44,67 Q68,58 98,46 L120,38 Q134,34 156,34 L194,35 Q210,37 225,48 "
           "L249,64 L304,69 Q332,72 339,81 Q343,89 341,104",
    "glass": "M74,61 L102,47 Q124,38 156,38 L192,39 Q206,41 219,51 L233,62 Z",
    "pillar": 154, "head": (323, 73, 15, 5), "tail": (17, 74, 9, 7), "wheels": (84, 274),
    "deck": (32, 68), "roof_y": 34, "hood": (249, 304, 66), "door": (108, 234), "roundel": (178, 88),
}
BODIES["tlx"] = {  # long, low performance sedan
    "top": "M14,104 L14,88 Q14,79 26,77 L68,73 Q84,70 100,58 L120,45 Q136,38 160,37 L202,37 Q218,38 232,49 "
           "L254,64 L308,69 Q334,72 341,81 Q345,89 343,104",
    "glass": "M106,60 L123,48 Q138,41 160,41 L200,41 Q214,42 226,52 L240,63 Z",
    "pillar": 166, "head": (325, 72, 15, 5), "tail": (15, 79, 10, 6), "wheels": (80, 278),
    "deck": (28, 75), "roof_y": 37, "hood": (254, 308, 66), "door": (114, 240), "roundel": (184, 88),
}
BODIES["super3"] = {  # hybrid mid-engine supercar: sharper wedge, bigger side intake
    "top": "M14,104 L14,88 Q15,80 28,78 L94,74 Q112,72 130,62 L150,52 Q164,47 184,47 L206,48 Q226,51 240,63 "
           "L264,78 L316,83 Q340,86 345,95 Q347,100 345,104",
    "glass": "M138,65 L154,56 Q166,51 184,51 L205,52 Q222,55 234,65 L240,72 Z",
    "pillar": None, "head": (330, 84, 13, 3), "tail": (15, 81, 11, 4), "wheels": (90, 276),
    "deck": (40, 76), "roof_y": 47, "hood": (264, 316, 80), "door": (152, 242), "roundel": (196, 96),
    "intake": "M104,86 L152,80 L150,101 L108,101 Z",
}
BODIES["gt3evo"] = {**BODIES["super3"], "gt3": True}
BODIES["proto"] = {  # closed-cockpit endurance prototype: long low nose, bubble canopy, shark fin
    "top": "M8,104 L8,82 Q10,74 22,72 L70,70 Q96,69 118,62 L140,50 Q152,44 170,43 L196,44 Q212,46 224,56 "
           "L240,70 Q270,80 316,88 Q340,92 348,98 L348,104",
    "glass": "M146,58 L156,50 Q166,46 180,46 L196,47 Q208,49 216,57 L222,64 Z",
    "pillar": None, "head": (332, 90, 13, 3), "tail": (9, 78, 9, 4), "wheels": (82, 286),
    "deck": (28, 72), "roof_y": 43, "hood": (240, 320, 80), "door": (150, 226), "roundel": (200, 92),
    "intake": "M100,86 L140,80 L138,100 L104,101 Z", "gt3": True,
    "fin": "M146,45 L46,55 L40,70 L70,69.5 Q96,68.5 118,62 L140,51 Z",
}
MID_ENGINE = {"super", "super2", "super3", "gt3", "gt3evo", "proto"}

# Visual tiers per part level (0..5)
WHEEL_STYLES = [
    ("steel", "#4a4d55", 0), ("5-spoke", "#c9ccd2", 5), ("6-spoke", "#d7d9de", 6),
    ("10-spoke forged", "#5b5f68", 10), ("6-spoke bronze", "#b0823c", 6), ("center-lock", "#c19a49", 7),
]
CALIPER = [None, "#2a2a2a", "#d62828", "#d62828", "#f4c430", "#f4c430"]


def _bottom(xs: tuple[int, int], arch: int, x0: int, x1: int, sill: int = 104) -> str:
    rear, front = xs
    return (f" L{x1},{sill} L{front + arch},{sill} A{arch},{arch} 0 0 0 {front - arch},{sill}"
            f" L{rear + arch},{sill} A{arch},{arch} 0 0 0 {rear - arch},{sill} L{x0},{sill} Z")


def _hex(c: str) -> tuple[int, int, int]:
    c = (c or "#888888").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return 136, 136, 136


def _mix(c: str, to: str, t: float) -> str:
    a, b = _hex(c), _hex(to)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _uid(*bits) -> str:
    return "c" + format(abs(hash(bits)) % 10 ** 8, "x")


def _wheel(cx: float, cy: float, tires: int, brakes: int, gt3: bool, uid: str = "w") -> str:
    style, rim, spokes = WHEEL_STYLES[min(tires, 5)]
    if gt3 and tires < 5:
        style, rim, spokes = WHEEL_STYLES[5]
    r_rim = 12.5 + min(tires, 5) * 0.35
    rt = R_TIRE + (1 if tires >= 3 else 0)
    lite, deep = _mix(rim, "#ffffff", .55), _mix(rim, "#000000", .45)
    out = [f'<defs><radialGradient id="{uid}t" cx=".5" cy=".5" r=".5"><stop offset=".72" stop-color="#16171b"/>'
           f'<stop offset=".9" stop-color="#25262b"/><stop offset="1" stop-color="#08080a"/></radialGradient>'
           f'<linearGradient id="{uid}r" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{lite}"/>'
           f'<stop offset=".5" stop-color="{rim}"/><stop offset="1" stop-color="{deep}"/></linearGradient></defs>',
           f'<circle cx="{cx}" cy="{cy}" r="{rt}" fill="url(#{uid}t)"/>',  # tyre with a rounded sidewall
           f'<path d="M{cx - rt + 3},{cy - 4} A{rt - 3},{rt - 3} 0 0 1 {cx - 4},{cy - rt + 3}" stroke="#ffffff" '
           f'stroke-opacity=".08" stroke-width="2" fill="none"/>',
           f'<circle cx="{cx}" cy="{cy}" r="{r_rim + 1}" fill="#0e0f12"/>',  # barrel depth
           f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="#1c1d22"/>']
    rotor = 7.5 + brakes * 0.7
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{rotor}" fill="#8a8e96"/>'
               f'<circle cx="{cx}" cy="{cy}" r="{rotor - 1.6}" fill="none" stroke="#a7abb2" stroke-width=".6"/>')
    if brakes >= 3:  # drilled / slotted discs
        for k in range(12):
            a = math.radians(k * 30)
            out.append(f'<circle cx="{cx + (rotor - 2.4) * math.cos(a):.1f}" cy="{cy + (rotor - 2.4) * math.sin(a):.1f}" '
                       f'r=".55" fill="#5c5f66"/>')
    cal = CALIPER[min(brakes, 5)]
    if cal:
        a0, a1 = math.radians(-62), math.radians(-8)
        ro = rotor + 1.5
        x0, y0 = cx + ro * math.cos(a0), cy + ro * math.sin(a0)
        x1, y1 = cx + ro * math.cos(a1), cy + ro * math.sin(a1)
        out.append(f'<path d="M{x0:.1f},{y0:.1f} A{ro},{ro} 0 0 1 {x1:.1f},{y1:.1f}" stroke="{cal}" '
                   f'stroke-width="{3.2 + brakes * 0.45:.1f}" fill="none" stroke-linecap="round"/>'
                   f'<path d="M{x0:.1f},{y0:.1f} A{ro},{ro} 0 0 1 {x1:.1f},{y1:.1f}" stroke="#ffffff" stroke-opacity=".3" '
                   f'stroke-width=".8" fill="none" transform="translate(-.4,-.6)"/>')
    if style == "steel":
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="url(#{uid}r)"/>'
                   f'<circle cx="{cx}" cy="{cy}" r="{r_rim - 3}" fill="none" stroke="{deep}" stroke-width="1"/>')
        for k in range(5):
            a = math.radians(k * 72)
            out.append(f'<circle cx="{cx + 7 * math.cos(a):.1f}" cy="{cy + 7 * math.sin(a):.1f}" r="1.6" fill="#24262b"/>')
        out.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="#2a2c31"/>')
    else:
        w = 3.0 if spokes <= 6 else 1.6
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="none" stroke="url(#{uid}r)" stroke-width="2.4"/>')
        for k in range(spokes):
            a = math.radians(k * 360 / spokes + 18)
            x_0, y_0 = cx + 3.2 * math.cos(a), cy + 3.2 * math.sin(a)
            x_1, y_1 = cx + (r_rim - 1) * math.cos(a), cy + (r_rim - 1) * math.sin(a)
            out.append(f'<line x1="{x_0:.1f}" y1="{y_0:.1f}" x2="{x_1:.1f}" y2="{y_1:.1f}" stroke="{deep}" '
                       f'stroke-width="{w + 1:.1f}" stroke-linecap="round"/>'
                       f'<line x1="{x_0:.1f}" y1="{y_0:.1f}" x2="{x_1:.1f}" y2="{y_1:.1f}" stroke="url(#{uid}r)" '
                       f'stroke-width="{w}" stroke-linecap="round"/>')
        hub = "#e9c46a" if style == "center-lock" else rim
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{4.2 if style == "center-lock" else 3.4}" fill="{hub}" stroke="{deep}" stroke-width=".6"/>')
        if style != "center-lock":  # lug nuts
            for k in range(5):
                a = math.radians(k * 72 + 36)
                out.append(f'<circle cx="{cx + 2 * math.cos(a):.1f}" cy="{cy + 2 * math.sin(a):.1f}" r=".5" fill="{deep}"/>')
    out.append(f'<ellipse cx="{cx - 4}" cy="{cy - 6}" rx="{r_rim * .55:.1f}" ry="{r_rim * .25:.1f}" fill="#ffffff" '
               f'opacity=".07" transform="rotate(-35 {cx - 4} {cy - 6})"/>')  # glint on the rim
    return "".join(out)


def car_svg(model_body: str, color: str, number, parts: dict, condition: int, width: int = 440,
            studio: bool = False) -> str:
    """Side profile with paint shading, reflections, glass glare, lights and every upgrade visible.
    studio=True adds a showroom floor, spotlight and reflection (for the Showroom)."""
    b = BODIES[model_body]
    gt3 = b.get("gt3", False)
    p = {k: int(v) for k, v in parts.items()}
    aero, eng, tires, brakes, turbo = p.get("aero", 0), p.get("engine", 0), p.get("tires", 0), p.get("brakes", 0), \
        p.get("turbo", 0)
    weight = p.get("weight", 0)
    drop = min(6, (tires + aero) // 2 + (3 if gt3 else 0))      # lowered stance
    arch = 26 if gt3 else 23
    rear_x, front_x = b["wheels"]
    wy = GROUND - R_TIRE
    x_start = int(b["top"][1:].split(",")[0])
    body = b["top"] + _bottom(b["wheels"], arch, x_start, 340)
    num = html.escape(str(number))
    dark = "#15161a"
    u = _uid(model_body, color, str(sorted(p.items())), condition, studio)
    hi, lo, sh = _mix(color, "#ffffff", .38), _mix(color, "#000000", .42), _mix(color, "#000000", .62)
    g = [f'<defs>'
         f'<linearGradient id="{u}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{hi}"/>'
         f'<stop offset=".38" stop-color="{color}"/><stop offset=".72" stop-color="{lo}"/><stop offset="1" stop-color="{sh}"/>'
         f'</linearGradient>'
         f'<linearGradient id="{u}g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3a4d63"/>'
         f'<stop offset=".55" stop-color="#121821"/><stop offset="1" stop-color="#0a0d12"/></linearGradient>'
         f'<radialGradient id="{u}h" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fffbe6"/>'
         f'<stop offset=".5" stop-color="#ffe9a8" stop-opacity=".6"/><stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/>'
         f'</radialGradient>'
         f'<radialGradient id="{u}t" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ff4d4d"/>'
         f'<stop offset=".55" stop-color="#d90429" stop-opacity=".55"/><stop offset="1" stop-color="#d90429" stop-opacity="0"/>'
         f'</radialGradient>'
         f'<clipPath id="{u}c"><path d="{body}"/></clipPath></defs>']

    # paint: shaded body, then reflections clipped to it
    g.append(f'<path d="{body}" fill="url(#{u}b)" stroke="#0b0c0e" stroke-width="1.4" stroke-linejoin="round"/>')
    g.append(f'<g clip-path="url(#{u}c)">'
             f'<path d="M0,84 C90,78 200,80 360,90 L360,95 C200,86 90,84 0,90 Z" fill="#ffffff" opacity=".16"/>'  # door reflection band
             f'<path d="M0,99 L360,99 L360,112 L0,112 Z" fill="#000000" opacity=".28"/>'  # rocker shadow
             f'<path d="M210,40 L250,40 L120,112 L80,112 Z" fill="#ffffff" opacity=".05"/>'  # studio light sweep
             f'</g>')
    g.append(f'<path d="{b["top"]}" fill="none" stroke="#ffffff" stroke-opacity=".38" stroke-width="1.2" '
             f'transform="translate(0,2.2)"/>')  # crisp shoulder highlight
    # wheel-arch depth
    for wx in (rear_x, front_x):
        g.append(f'<path d="M{wx - arch},104 A{arch},{arch} 0 0 1 {wx + arch},104" fill="none" stroke="#000" '
                 f'stroke-opacity=".55" stroke-width="3.2"/>')
    # weight 2+: carbon roof
    if weight >= 2 and not b.get("roadster"):
        ry = b["roof_y"]
        g.append(f'<path d="M{b["door"][0] + 10},{ry + 1} L{b["door"][1] - 30},{ry + 1}" stroke="#1d1e22" '
                 f'stroke-width="4.4" stroke-linecap="round"/><path d="M{b["door"][0] + 12},{ry} L{b["door"][1] - 32},{ry}" '
                 f'stroke="#ffffff" stroke-opacity=".18" stroke-width=".8" stroke-dasharray="2 1.4"/>')
    if b.get("fin"):  # prototype shark fin along the engine cover
        g.append(f'<path d="{b["fin"]}" fill="{lo}" stroke="#0b0c0e" stroke-width="1"/>'
                 f'<path d="{b["fin"]}" fill="none" stroke="#ffffff" stroke-opacity=".18" stroke-width=".6" '
                 f'transform="translate(0,1)"/>')
    # glass with glare
    g.append(f'<path d="{b["glass"]}" fill="url(#{u}g)" stroke="#0b0c0e" stroke-width="1"/>')
    g.append(f'<clipPath id="{u}w"><path d="{b["glass"]}"/></clipPath><g clip-path="url(#{u}w)">'
             f'<path d="M130,30 L150,30 L118,70 L98,70 Z" fill="#ffffff" opacity=".18"/>'
             f'<path d="M160,30 L168,30 L136,70 L128,70 Z" fill="#ffffff" opacity=".1"/>'
             f'<path d="M190,30 L222,30 L200,70 L168,70 Z" fill="#9fc3e6" opacity=".08"/></g>')
    if b["pillar"]:
        g.append(f'<line x1="{b["pillar"]}" y1="40" x2="{b["pillar"] + 2}" y2="62" stroke="#0e0f12" stroke-width="5"/>')
    # weight 4+: roll cage visible through the glass
    if weight >= 4 and not b.get("roadster"):
        x0, x1 = b["door"][0] + 20, b["door"][1] - 40
        g.append(f'<path d="M{x0},60 L{x0 + 12},{b["roof_y"] + 8} L{x1},{b["roof_y"] + 8} L{x1 + 10},60" '
                 f'stroke="#e5e5e5" stroke-width="1.6" fill="none" opacity=".8"/>')
    if b.get("roadster"):  # roll hoops + folded soft top + a seat back
        g.append('<path d="M128,68 Q132,56 140,56 Q148,56 150,68 Z M152,68 Q156,56 164,56 Q172,56 174,68 Z" fill="#26272c"/>'
                 '<path d="M131,66 Q134,58 140,58" stroke="#ffffff" stroke-opacity=".15" fill="none"/>'
                 '<path d="M100,72 Q104,64 118,64 L124,68 Z" fill="#1d1e22"/>'
                 '<path d="M182,68 Q186,60 194,60 L196,68 Z" fill="#7a1d1d"/>')
    # panel lines: doors, fender seams, fuel door, handle, mirror, side marker
    d0, d1 = b["door"]
    g.append(f'<path d="M{d0},64 L{d0 + 4},101 M{d1},62 L{d1 - 4},101" stroke="#000" stroke-opacity=".45" stroke-width="1"/>'
             f'<path d="M{d0 + 1},64 L{d0 + 5},101" stroke="#ffffff" stroke-opacity=".12" stroke-width=".6" transform="translate(1,0)"/>'
             f'<path d="M{front_x - arch - 6},70 Q{front_x - arch - 2},88 {front_x - arch + 2},101" stroke="#000" stroke-opacity=".3" fill="none"/>'
             f'<path d="M{rear_x + arch + 6},72 Q{rear_x + arch + 2},88 {rear_x + arch - 2},101" stroke="#000" stroke-opacity=".3" fill="none"/>')
    g.append(f'<rect x="{d1 - 30}" y="72" width="11" height="2.6" rx="1.2" fill="#000" opacity=".45"/>'
             f'<rect x="{d1 - 30}" y="72" width="11" height="1" rx=".5" fill="#ffffff" opacity=".2"/>')
    if not b.get("roadster"):
        g.append(f'<circle cx="{rear_x + arch + 14}" cy="74" r="3" fill="none" stroke="#000" stroke-opacity=".35"/>')  # fuel door
    mx = d1 - 4 if model_body not in MID_ENGINE else d1 - 2
    g.append(f'<path d="M{mx},62 l9,-2 q3,0 2,4 l-9,3 Z" fill="url(#{u}b)" stroke="#0b0c0e" stroke-width=".8"/>')  # mirror
    g.append(f'<rect x="{front_x + arch + 4}" y="82" width="6" height="2.2" rx="1" fill="#ff9f1c" opacity=".85"/>')  # marker
    # super/gt3 side intake
    if b.get("intake"):
        g.append(f'<path d="{b["intake"]}" fill="#0c0d10"/><path d="{b["intake"]}" fill="none" stroke="#ffffff" '
                 f'stroke-opacity=".15" stroke-width=".8"/>')
        ix = int(b["intake"].split(",")[0][1:])
        for k in range(4):
            g.append(f'<path d="M{ix + 6 + k * 7},{89 + k * .2:.1f} l-3,10" stroke="#2a2c31" stroke-width="1.2"/>')
    # front: grille / air dam, rear: bumper reflector and diffuser shadow
    g.append('<path d="M318,92 L340,93 L340,102 L314,102 Z" fill="#0c0d10" opacity=".9"/>'
             '<path d="M320,95 L338,95.5 M320,98 L338,98.5" stroke="#3a3d44" stroke-width=".8"/>')
    g.append(f'<rect x="{x_start + 1}" y="94" width="7" height="2" rx="1" fill="#b3121f" opacity=".85"/>')
    # engine visuals
    h0, h1, hy = b["hood"]
    if eng >= 2:
        g.append(f'<path d="M{h0 + 18},{hy + 1} l10,-1 M{h0 + 22},{hy + 3} l10,-1" stroke="{dark}" stroke-width="2"/>')
    if eng >= 3:  # side stripe with a pinstripe
        g.append('<path d="M24,94 L336,94" stroke="#ffffff" stroke-opacity=".9" stroke-width="3"/>'
                 '<path d="M24,97.4 L336,97.4" stroke="#ffffff" stroke-opacity=".55" stroke-width=".8"/>')
    if eng >= 4:  # hood bulge / scoop
        g.append(f'<path d="M{h0 + 6},{hy} Q{(h0 + h1) / 2},{hy - 5} {h1 - 10},{hy + 1}" fill="none" stroke="{dark}" '
                 f'stroke-width="2.5"/>')
    if eng >= 5:  # carbon hood
        g.append(f'<path d="M{h0},{hy - 1} L{h1},{hy + 3}" stroke="#202124" stroke-width="5" stroke-linecap="round"/>'
                 f'<path d="M{h0 + 2},{hy - 2} L{h1 - 2},{hy + 2}" stroke="#ffffff" stroke-opacity=".15" stroke-width=".8" stroke-dasharray="2 1.4"/>')
    # lights with glow
    hx, hyy, hw, hh = b["head"]
    g.append(f'<ellipse cx="{hx + hw / 2 + 4}" cy="{hyy + hh / 2}" rx="{hw + 6}" ry="{hh + 5}" fill="url(#{u}h)" opacity=".75"/>'
             f'<rect x="{hx}" y="{hyy}" width="{hw}" height="{hh}" rx="2" fill="#eef1f5" stroke="#0b0c0e" stroke-width=".6"/>'
             f'<rect x="{hx + 1}" y="{hyy + hh - 1.6}" width="{hw - 2}" height="1.1" rx=".5" fill="#ffffff"/>'
             f'<circle cx="{hx + hw * .35}" cy="{hyy + hh * .45}" r="{min(hh, hw) * .28:.1f}" fill="#c8d6e8"/>')
    tx, ty, tw, th = b["tail"]
    g.append(f'<ellipse cx="{tx + tw / 2 - 2}" cy="{ty + th / 2}" rx="{tw + 5}" ry="{th + 4}" fill="url(#{u}t)" opacity=".7"/>'
             f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="2" fill="#c1121f" stroke="#5a0710" stroke-width=".5"/>'
             f'<rect x="{tx + 1}" y="{ty + 1}" width="{tw - 2}" height="{max(1, th * .3):.1f}" rx=".6" fill="#ff6b6b"/>')
    # number roundel
    rx, ry = b["roundel"]
    g.append(f'<circle cx="{rx}" cy="{ry - 6}" r="10" fill="#fff" stroke="#111" stroke-width="1.2"/>'
             f'<text x="{rx}" y="{ry - 2}" font-size="11" font-family="Arial,sans-serif" font-weight="700" '
             f'text-anchor="middle" fill="#111">{num}</text>')
    # aero
    if aero >= 1 or gt3:  # front lip / splitter
        ext = 10 if (aero >= 5 or gt3) else 5
        g.append(f'<path d="M300,104 L{340 + ext},104 L{338 + ext},107 L300,107 Z" fill="{dark}"/>'
                 f'<path d="M300,104 L{340 + ext},104" stroke="#ffffff" stroke-opacity=".15" stroke-width=".7"/>')
    if aero >= 2:  # side skirt
        g.append(f'<path d="M{rear_x + arch},103 L{front_x - arch},103" stroke="{dark}" stroke-width="4"/>')
    if aero >= 3:  # canards
        g.append('<path d="M330,90 l12,-2 l-2,4 Z M332,97 l11,-1 l-2,4 Z" fill="#1b1c20"/>')
    if aero >= 5 or gt3:  # rear diffuser
        g.append('<path d="M14,104 L44,104 L40,110 M24,104 L20,110 M34,104 L30,110" stroke="#111" '
                 'stroke-width="2.5" fill="none"/>')
    # rear wing tiers (factory hatch & GT3 have their own)
    dx, dy = b["deck"]
    wing_tier = max(aero, 4 if gt3 else 0, 3 if model_body == "hatch" else 0)
    if wing_tier == 2:
        g.append(f'<path d="M{dx - 10},{dy} L{dx + 16},{dy - 3} L{dx + 16},{dy} Z" fill="{dark}"/>')  # lip
    elif wing_tier == 3:
        g.append(f'<rect x="{dx - 14}" y="{dy - 10}" width="34" height="4" rx="2" fill="{dark}"/>'
                 f'<rect x="{dx - 14}" y="{dy - 10}" width="34" height="1.2" rx=".6" fill="#ffffff" opacity=".18"/>'
                 f'<rect x="{dx - 4}" y="{dy - 6}" width="3" height="7" fill="{dark}"/>'
                 f'<rect x="{dx + 10}" y="{dy - 6}" width="3" height="7" fill="{dark}"/>')
    elif wing_tier >= 4:  # swan-neck GT wing
        big = wing_tier >= 5
        top = dy - (20 if big else 15)
        span = 52 if big else 42
        g.append(f'<path d="M{dx - 22},{top} L{dx - 22 + span},{top - 3} L{dx - 22 + span},{top + 2} '
                 f'L{dx - 22},{top + 4} Z" fill="{dark}" stroke="#666" stroke-width=".6"/>'
                 f'<path d="M{dx - 22},{top + .4} L{dx - 22 + span},{top - 2.6}" stroke="#ffffff" stroke-opacity=".22" stroke-width=".7"/>'
                 f'<rect x="{dx - 24}" y="{top - 5}" width="3" height="13" fill="{dark}"/>'
                 f'<path d="M{dx - 4},{top + 2} Q{dx - 8},{dy - 6} {dx + 2},{dy}" stroke="{dark}" stroke-width="3" fill="none"/>'
                 f'<path d="M{dx + 12},{top + 1} Q{dx + 8},{dy - 6} {dx + 18},{dy}" stroke="{dark}" stroke-width="3" fill="none"/>')
    # turbo / exhaust
    if turbo >= 1:
        tip = 3 + turbo
        g.append(f'<rect x="{10 - tip}" y="98" width="{tip + 10}" height="5" rx="2.4" fill="#c4c7cd" stroke="#555" stroke-width=".6"/>'
                 f'<ellipse cx="{10 - tip + 1}" cy="100.5" rx="1.2" ry="2" fill="#2a2b30"/>')
    if turbo >= 3:  # front-mount intercooler peeking through the bumper
        g.append('<path d="M326,92 L340,92 L340,100 L326,100 Z" fill="#3b3f46"/>'
                 '<path d="M328,94 L338,94 M328,96 L338,96 M328,98 L338,98" stroke="#7d828c" stroke-width=".8"/>')
    if turbo >= 4:
        size = 6 + (turbo - 3) * 5
        g.append(f'<path d="M{8 - 3},100 l-{size},-3 l{size * .4},3 l-{size},3 Z" fill="#ff9f1c"/>'
                 f'<path d="M{8 - 3},100 l-{size * .55},-1.5 l{size * .2},1.5 l-{size * .55},1.5 Z" fill="#ffe66d"/>')
    # weight 3+: red tow hook
    if weight >= 3:
        g.append('<path d="M341,98 l6,0 l0,4 l-6,0" stroke="#d62828" stroke-width="2" fill="none"/>')
    # damage
    if condition < 60:
        g.append('<path d="M200,82 l18,8 M240,80 l10,14 M110,88 l14,6" stroke="#111" stroke-width="2"/>')
    if condition < 30:
        g.append('<circle cx="300" cy="56" r="9" fill="#777" opacity=".5"/><circle cx="314" cy="40" r="12" fill="#777" opacity=".35"/>')

    wheels = (_wheel(rear_x, wy, tires, brakes, gt3, u + "a") + _wheel(front_x, wy, tires, brakes, gt3, u + "f"))
    car_g = f'<g transform="translate(0,{drop})">{"".join(g)}</g>{wheels}'
    shadow = (f'<ellipse cx="180" cy="{GROUND + 1}" rx="170" ry="5" fill="#000" opacity=".45"/>'
              f'<ellipse cx="{rear_x}" cy="{GROUND}" rx="24" ry="3" fill="#000" opacity=".5"/>'
              f'<ellipse cx="{front_x}" cy="{GROUND}" rx="24" ry="3" fill="#000" opacity=".5"/>')
    if not studio:
        return (f'<svg viewBox="-6 20 368 112" width="100%" style="max-width:{width}px" xmlns="http://www.w3.org/2000/svg">'
                f'{shadow}{car_g}</svg>')
    floor = (f'<defs><radialGradient id="{u}s" cx=".5" cy=".35" r=".75"><stop offset="0" stop-color="#3a3f4c"/>'
             f'<stop offset=".55" stop-color="#1a1d24"/><stop offset="1" stop-color="#0d0f13"/></radialGradient>'
             f'<linearGradient id="{u}f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity=".18"/>'
             f'<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient>'
             f'<linearGradient id="{u}m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".22"/>'
             f'<stop offset=".6" stop-color="#fff" stop-opacity="0"/></linearGradient>'
             f'<mask id="{u}k"><rect x="-20" y="{GROUND}" width="400" height="60" fill="url(#{u}m)"/></mask></defs>'
             f'<rect x="-20" y="-10" width="400" height="200" fill="url(#{u}s)"/>'
             f'<path d="M110,-10 L250,-10 L320,{GROUND} L40,{GROUND} Z" fill="url(#{u}f)" opacity=".5"/>'  # spotlight cone
             f'<rect x="-20" y="{GROUND}" width="400" height="60" fill="#0b0c10"/>'
             f'<path d="M-20,{GROUND} L380,{GROUND}" stroke="#ffffff" stroke-opacity=".08"/>')
    reflection = (f'<g mask="url(#{u}k)"><g transform="translate(0,{2 * GROUND}) scale(1,-1)">{car_g}</g></g>')
    return (f'<svg viewBox="-14 6 384 158" width="100%" style="max-width:{width}px;border-radius:14px" '
            f'xmlns="http://www.w3.org/2000/svg">{floor}{reflection}{shadow}{car_g}</svg>')


# ── top-down sprite for the focus-timer track: same paint, number and body as your Garage car ──
TOP = {  # length, width, cabin (x0, x1) from the rear, nose taper, open cockpit
    "sedan": (24, 11, (-5, 5), 3, False), "coupe": (23, 11, (-3, 5), 3.5, False),
    "hatch": (21, 11, (-7, 5), 2.5, False), "roadster": (21, 10, (-3, 3), 3.5, True),
    "super": (25, 12, (-1, 7), 4.5, False), "super2": (25, 12, (-1, 7), 5, False),
    "gt3": (26, 13, (-1, 7), 4.5, False),
    "rsx": (22, 11, (-4, 5), 3, False), "tsx": (24, 11, (-5, 5), 3, False), "integra_s": (24, 11, (-4, 5), 3.2, False),
    "tlx": (26, 12, (-5, 6), 3.5, False), "super3": (25, 12, (-1, 7), 5, False), "gt3evo": (26, 13, (-1, 7), 4.5, False),
    "proto": (30, 13, (1, 8), 7, False),
}


def car_topdown(model_body: str, color: str, number, parts: dict) -> str:
    """SVG <g> content centred on (0,0), nose pointing +x. Rear wing from aero 3+ (always on a GT3); wider tyres
    from tyres 3+; a stripe from engine 4+."""
    L, W, (c0, c1), taper, open_ = TOP.get(model_body, TOP["sedan"])
    p = {k: int(v) for k, v in (parts or {}).items()}
    gt3 = model_body in ("gt3", "gt3evo", "proto")
    h, w = L / 2, W / 2
    tw = 1.4 if p.get("tires", 0) >= 3 or gt3 else 1.0
    num = html.escape(str(number))[:3]
    out = []
    for x in (-h + 4.5, h - 5):  # tyres peeking out at the four corners
        for y in (-w - tw + .6, w - .6):
            out.append(f'<rect x="{x - 2.4:.1f}" y="{y:.1f}" width="4.8" height="{tw:.1f}" rx=".6" fill="#0e1015"/>')
    body = (f"M{-h:.1f},{-w + 1.5:.1f} Q{-h:.1f},{-w:.1f} {-h + 2:.1f},{-w:.1f} L{h - taper:.1f},{-w:.1f} "
            f"Q{h:.1f},{-w + 1:.1f} {h:.1f},{-w + 3:.1f} L{h:.1f},{w - 3:.1f} Q{h:.1f},{w - 1:.1f} {h - taper:.1f},{w:.1f} "
            f"L{-h + 2:.1f},{w:.1f} Q{-h:.1f},{w:.1f} {-h:.1f},{w - 1.5:.1f} Z")
    out.append(f'<path d="{body}" fill="{color}" stroke="#0d0e10" stroke-width=".6"/>')
    if p.get("engine", 0) >= 4 or gt3:
        out.append(f'<rect x="{-h + 1:.1f}" y="-.9" width="{L - 2:.1f}" height="1.8" fill="#ffffff" opacity=".85"/>')
    if open_:
        out.append(f'<rect x="{c0:.1f}" y="{-w + 2:.1f}" width="{c1 - c0:.1f}" height="{W - 4:.1f}" rx="1.5" fill="#14161c"/>')
        out.append(f'<rect x="{c1 - .6:.1f}" y="{-w + 1.6:.1f}" width="1.2" height="{W - 3.2:.1f}" rx=".5" fill="#9fb3c8"/>')
    else:
        out.append(f'<rect x="{c0:.1f}" y="{-w + 1.6:.1f}" width="{c1 - c0:.1f}" height="{W - 3.2:.1f}" rx="2" fill="#1a1e26"/>')
        out.append(f'<rect x="{c1 - 2.2:.1f}" y="{-w + 2.2:.1f}" width="2" height="{W - 4.4:.1f}" rx=".8" fill="#8fb0cc" opacity=".55"/>')
        out.append(f'<circle cx="{(c0 + c1) / 2 - .5:.1f}" cy="0" r="2.9" fill="#ffffff"/>'
                   f'<text x="{(c0 + c1) / 2 - .5:.1f}" y="1.25" font-size="{3.6 if len(num) < 3 else 2.8}" '
                   f'font-weight="800" text-anchor="middle" fill="#111" font-family="system-ui,sans-serif">{num}</text>')
    if p.get("aero", 0) >= 3 or gt3:
        out.append(f'<rect x="{-h - 2.2:.1f}" y="{-w - .4:.1f}" width="1.8" height="{W + .8:.1f}" rx=".5" fill="#111318"/>')
    out.append(f'<rect x="{h - 1.3:.1f}" y="{-w + 1.6:.1f}" width="1" height="2" fill="#fff6c8"/>'
               f'<rect x="{h - 1.3:.1f}" y="{w - 3.6:.1f}" width="1" height="2" fill="#fff6c8"/>')
    return "".join(out)
