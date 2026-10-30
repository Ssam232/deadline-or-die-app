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
BODIES["gt3"] = {**BODIES["super"], "gt3": True}

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


def _wheel(cx: float, cy: float, tires: int, brakes: int, gt3: bool) -> str:
    style, rim, spokes = WHEEL_STYLES[min(tires, 5)]
    if gt3 and tires < 5:
        style, rim, spokes = WHEEL_STYLES[5]
    r_rim = 12.5 + min(tires, 5) * 0.35
    out = [f'<circle cx="{cx}" cy="{cy}" r="{R_TIRE + (1 if tires >= 3 else 0)}" fill="#0b0b0d"/>',
           f'<circle cx="{cx}" cy="{cy}" r="{R_TIRE - 2}" fill="none" stroke="#2c2d31" stroke-width="1.2"/>',
           f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="#1a1b1f"/>']
    rotor = 7.5 + brakes * 0.7
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{rotor}" fill="#7b7f87"/>')
    if brakes >= 5:
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{rotor - 2}" fill="none" stroke="#5c5f66" stroke-dasharray="1.5 2"/>')
    cal = CALIPER[min(brakes, 5)]
    if cal:
        a0, a1 = math.radians(-60), math.radians(-10)
        ro = rotor + 1.5
        x0, y0 = cx + ro * math.cos(a0), cy + ro * math.sin(a0)
        x1, y1 = cx + ro * math.cos(a1), cy + ro * math.sin(a1)
        out.append(f'<path d="M{x0:.1f},{y0:.1f} A{ro},{ro} 0 0 1 {x1:.1f},{y1:.1f}" stroke="{cal}" '
                   f'stroke-width="{3 + brakes * 0.4:.1f}" fill="none" stroke-linecap="round"/>')
    if style == "steel":
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="{rim}"/>')
        for k in range(5):
            a = math.radians(k * 72)
            out.append(f'<circle cx="{cx + 7 * math.cos(a):.1f}" cy="{cy + 7 * math.sin(a):.1f}" r="1.6" fill="#24262b"/>')
        out.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="#2a2c31"/>')
    else:
        w = 2.6 if spokes <= 6 else 1.4
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="none" stroke="{rim}" stroke-width="2"/>')
        for k in range(spokes):
            a = math.radians(k * 360 / spokes + 18)
            out.append(f'<line x1="{cx + 3 * math.cos(a):.1f}" y1="{cy + 3 * math.sin(a):.1f}" '
                       f'x2="{cx + (r_rim - 1) * math.cos(a):.1f}" y2="{cy + (r_rim - 1) * math.sin(a):.1f}" '
                       f'stroke="{rim}" stroke-width="{w}" stroke-linecap="round"/>')
        hub = "#e9c46a" if style == "center-lock" else rim
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{3.6 if style == "center-lock" else 3}" fill="{hub}"/>')
    return "".join(out)


def car_svg(model_body: str, color: str, number, parts: dict, condition: int, width: int = 440) -> str:
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
    body = b["top"] + _bottom(b["wheels"], arch, int(b["top"][1:].split(",")[0]), 340)
    num = html.escape(str(number))
    dark = "#15161a"
    g = []  # everything inside the body group (moved down by `drop`)

    g.append(f'<path d="{body}" fill="{color}" stroke="#0d0e10" stroke-width="1.6" stroke-linejoin="round"/>')
    # subtle highlight along the shoulder
    g.append(f'<path d="{b["top"]}" fill="none" stroke="#ffffff" stroke-opacity=".18" stroke-width="2" '
             f'transform="translate(0,3)"/>')
    # weight 2+: carbon roof
    if weight >= 2 and not b.get("roadster"):
        ry = b["roof_y"]
        g.append(f'<path d="M{b["door"][0] + 10},{ry + 1} L{b["door"][1] - 30},{ry + 1}" stroke="{dark}" '
                 f'stroke-width="4" stroke-linecap="round"/>')
    # glass
    g.append(f'<path d="{b["glass"]}" fill="#1c2733" stroke="#0d0e10" stroke-width="1"/>')
    if b["pillar"]:
        g.append(f'<line x1="{b["pillar"]}" y1="40" x2="{b["pillar"] + 2}" y2="62" stroke="{color}" stroke-width="5"/>')
    # weight 4+: roll cage visible through the glass
    if weight >= 4 and not b.get("roadster"):
        x0, x1 = b["door"][0] + 20, b["door"][1] - 40
        g.append(f'<path d="M{x0},60 L{x0 + 12},{b["roof_y"] + 8} L{x1},{b["roof_y"] + 8} L{x1 + 10},60" '
                 f'stroke="#e5e5e5" stroke-width="1.6" fill="none" opacity=".8"/>')
    if b.get("roadster"):  # roll hoops + folded soft top
        g.append('<path d="M128,68 Q132,56 140,56 Q148,56 150,68 Z M152,68 Q156,56 164,56 Q172,56 174,68 Z" fill="#26272c"/>')
        g.append('<path d="M100,72 Q104,64 118,64 L124,68 Z" fill="#202126"/>')
    # door line + handle
    d0, d1 = b["door"]
    g.append(f'<path d="M{d0},66 L{d0 + 4},100 M{d1},64 L{d1 - 4},100" stroke="#000" stroke-opacity=".35" stroke-width="1"/>')
    g.append(f'<rect x="{d1 - 30}" y="72" width="10" height="2.5" rx="1" fill="#000" opacity=".4"/>')
    # super/gt3 side intake
    if b.get("intake"):
        g.append(f'<path d="{b["intake"]}" fill="{dark}"/>')
    # engine visuals
    h0, h1, hy = b["hood"]
    if eng >= 2:
        g.append(f'<path d="M{h0 + 18},{hy + 1} l10,-1 M{h0 + 22},{hy + 3} l10,-1" stroke="{dark}" stroke-width="2"/>')
    if eng >= 3:  # side stripe
        g.append(f'<path d="M24,94 L336,94" stroke="#ffffff" stroke-opacity=".85" stroke-width="3"/>')
    if eng >= 4:  # hood bulge / scoop
        g.append(f'<path d="M{h0 + 6},{hy} Q{(h0 + h1) / 2},{hy - 5} {h1 - 10},{hy + 1}" fill="none" stroke="{dark}" '
                 f'stroke-width="2.5"/>')
    if eng >= 5:  # carbon hood
        g.append(f'<path d="M{h0},{hy - 1} L{h1},{hy + 3}" stroke="#202124" stroke-width="5" stroke-linecap="round"/>')
    # lights
    hx, hyy, hw, hh = b["head"]
    g.append(f'<rect x="{hx}" y="{hyy}" width="{hw}" height="{hh}" rx="2" fill="#f1f3d9" stroke="#0d0e10" stroke-width=".6"/>')
    tx, ty, tw, th = b["tail"]
    g.append(f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="2" fill="#c1121f"/>')
    # number roundel
    rx, ry = b["roundel"]
    g.append(f'<circle cx="{rx}" cy="{ry - 6}" r="10" fill="#fff" stroke="#111" stroke-width="1.2"/>'
             f'<text x="{rx}" y="{ry - 2}" font-size="11" font-family="Arial,sans-serif" font-weight="700" '
             f'text-anchor="middle" fill="#111">{num}</text>')
    # aero
    if aero >= 1 or gt3:  # front lip / splitter
        ext = 10 if (aero >= 5 or gt3) else 5
        g.append(f'<path d="M300,104 L{340 + ext},104 L{338 + ext},107 L300,107 Z" fill="{dark}"/>')
    if aero >= 2:  # side skirt
        g.append(f'<path d="M{rear_x + arch},103 L{front_x - arch},103" stroke="{dark}" stroke-width="4"/>')
    if aero >= 3:  # canards
        g.append(f'<path d="M330,90 l12,-2 l-2,4 Z M332,97 l11,-1 l-2,4 Z" fill="{dark}"/>')
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
                 f'<rect x="{dx - 4}" y="{dy - 6}" width="3" height="7" fill="{dark}"/>'
                 f'<rect x="{dx + 10}" y="{dy - 6}" width="3" height="7" fill="{dark}"/>')
    elif wing_tier >= 4:  # swan-neck GT wing
        big = wing_tier >= 5
        top = dy - (20 if big else 15)
        span = 52 if big else 42
        g.append(f'<path d="M{dx - 22},{top} L{dx - 22 + span},{top - 3} L{dx - 22 + span},{top + 2} '
                 f'L{dx - 22},{top + 4} Z" fill="{dark}" stroke="#666" stroke-width=".6"/>'
                 f'<rect x="{dx - 24}" y="{top - 5}" width="3" height="13" fill="{dark}"/>'
                 f'<path d="M{dx - 4},{top + 2} Q{dx - 8},{dy - 6} {dx + 2},{dy}" stroke="{dark}" stroke-width="3" fill="none"/>'
                 f'<path d="M{dx + 12},{top + 1} Q{dx + 8},{dy - 6} {dx + 18},{dy}" stroke="{dark}" stroke-width="3" fill="none"/>')
    # turbo / exhaust
    if turbo >= 1:
        tip = 3 + turbo
        g.append(f'<rect x="{10 - tip}" y="98" width="{tip + 10}" height="5" rx="2" fill="#b9bcc2" stroke="#555" stroke-width=".6"/>')
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

    wheels = _wheel(rear_x, wy, tires, brakes, gt3) + _wheel(front_x, wy, tires, brakes, gt3)
    return (f'<svg viewBox="-6 20 368 112" width="100%" style="max-width:{width}px" xmlns="http://www.w3.org/2000/svg">'
            f'<ellipse cx="180" cy="{GROUND + 2}" rx="168" ry="6" fill="#000" opacity=".28"/>'
            f'<g transform="translate(0,{drop})">{"".join(g)}</g>{wheels}</svg>')


# ── top-down sprite for the focus-timer track: same paint, number and body as your Garage car ──
TOP = {  # length, width, cabin (x0, x1) from the rear, nose taper, open cockpit
    "sedan": (24, 11, (-5, 5), 3, False), "coupe": (23, 11, (-3, 5), 3.5, False),
    "hatch": (21, 11, (-7, 5), 2.5, False), "roadster": (21, 10, (-3, 3), 3.5, True),
    "super": (25, 12, (-1, 7), 4.5, False), "gt3": (26, 13, (-1, 7), 4.5, False),
}


def car_topdown(model_body: str, color: str, number, parts: dict) -> str:
    """SVG <g> content centred on (0,0), nose pointing +x. Rear wing from aero 3+ (always on a GT3); wider tyres
    from tyres 3+; a stripe from engine 4+."""
    L, W, (c0, c1), taper, open_ = TOP.get(model_body, TOP["sedan"])
    p = {k: int(v) for k, v in (parts or {}).items()}
    gt3 = model_body == "gt3"
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
