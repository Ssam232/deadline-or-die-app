"""
🎨 Car art — stylized side profiles drawn to scale from each real car's proportions (no badges or logos). Every upgrade is visible on the car.

Front of the car faces right. Pure functions returning SVG strings.
"""
from __future__ import annotations

import html
import math

GROUND = 124
R_TIRE = 19

# Upper body profile (rear-bottom → over the top → front-bottom), glass, light positions, wheel x's.
# ── side profiles from real proportions (metres) — stylized and badge-free, but shaped like the real cars ──
# L length · H height · WB wheelbase · FO front overhang · TD tyre diameter · SILL rocker height
# OUT: the body outline from the FRONT bumper's bottom, over the top, to the REAR bumper's bottom: (f, z) where
#      f = metres back from the front bumper and z = metres above the ground. A third item "c" = a sharp corner.
# DLO: the side glass (day-light opening) the same way. Everything else is placed from these numbers.
PROFILES = {
    "sedan": dict(  # noqa
        WHEEL=("twin", "#3a3d44", 5), LAMP="slim", EXH="twin",   # Civic Si: long hood, sleek fastback-style sedan roof, short decklid
        L=4.67, H=1.41, WB=2.735, FO=0.97, TD=0.65, SILL=0.21,
        OUT=[(0.04, 0.25, "c"), (0.0, 0.42), (0.03, 0.62), (0.16, 0.75), (0.6, 0.83), (1.15, 0.95, "c"),
             (1.55, 1.18), (1.92, 1.37), (2.45, 1.41), (3.0, 1.37), (3.55, 1.2), (3.98, 1.04, "c"), (4.42, 1.0),
             (4.63, 0.97, "c"), (4.67, 0.8), (4.66, 0.45), (4.62, 0.26, "c")],
        DLO=[(1.27, 0.98), (1.92, 1.31), (2.98, 1.31), (3.62, 1.07), (1.27, 0.96)],
        B=2.42, DOORS=[1.25, 2.42, 3.35], BELT=0.98, HEAD=(0.03, 0.34, 0.66, 0.73), TAIL=(4.45, 4.67, 0.84, 0.93),
        HOOD=(0.25, 1.05), ROOF=(2.0, 2.95), DECK=4.4, CAP=4.0),
    "coupe": dict(  # noqa
        WHEEL=("spoke", "#efeee8", 5), LAMP="tall", EXH="single",   # Integra Type R (DC2): low three-door with a sloping hatch and a factory wing
        L=4.38, H=1.32, WB=2.57, FO=0.92, TD=0.60, SILL=0.2,
        OUT=[(0.04, 0.23, "c"), (0.0, 0.40), (0.03, 0.57), (0.2, 0.68), (0.62, 0.76), (1.12, 0.88, "c"),
             (1.45, 1.08), (1.78, 1.29), (2.3, 1.32), (2.78, 1.29), (3.45, 1.07), (3.88, 0.99, "c"), (4.3, 0.96),
             (4.38, 0.8), (4.37, 0.45), (4.33, 0.25, "c")],
        DLO=[(1.17, 0.9), (1.78, 1.23), (2.7, 1.23), (3.3, 1.03), (1.17, 0.88)],
        B=2.6, DOORS=[1.15, 2.6], BELT=0.9, HEAD=(0.03, 0.36, 0.59, 0.65), TAIL=(4.18, 4.38, 0.82, 0.92),
        HOOD=(0.25, 1.0), ROOF=(1.95, 2.75), DECK=4.02, CAP=3.6, WING=3),
    "roadster": dict(  # noqa
        WHEEL=("spoke", "#c9ccd2", 6), LAMP="tall", EXH="twin",   # S2000: long hood, cockpit set far back, roll hoops, short tail
        L=4.12, H=1.27, WB=2.40, FO=0.83, TD=0.63, SILL=0.19, OPEN=True,
        OUT=[(0.04, 0.23, "c"), (0.0, 0.42), (0.04, 0.58), (0.26, 0.7), (0.8, 0.8), (1.55, 0.92, "c"),
             (2.02, 1.11, "c"), (2.08, 1.11, "c"), (2.2, 0.95, "c"), (3.2, 0.95), (3.5, 0.97), (3.98, 0.98, "c"),
             (4.11, 0.92), (4.12, 0.74), (4.11, 0.42), (4.07, 0.24, "c")],
        DLO=[(1.6, 0.93), (2.0, 1.1), (2.06, 1.1), (1.72, 0.93)],
        B=None, DOORS=[1.6, 2.75], BELT=0.94, HEAD=(0.04, 0.42, 0.6, 0.67), TAIL=(3.95, 4.12, 0.8, 0.9),
        HOOD=(0.35, 1.45), ROOF=None, DECK=3.9, CAP=None, HOOPS=(2.82, 3.02), HOOP_Z=1.12),
    "hatch": dict(  # noqa
        WHEEL=("spoke", "#1e1f23", 10), LAMP="slim", EXH="center3",   # Civic Type R (FL5): fastback five-door, flared arches, wing on tall stands
        L=4.59, H=1.41, WB=2.735, FO=1.0, TD=0.68, SILL=0.18,
        OUT=[(0.04, 0.21, "c"), (0.0, 0.38), (0.03, 0.6), (0.18, 0.74), (0.62, 0.82), (1.15, 0.94, "c"),
             (1.55, 1.17), (1.92, 1.37), (2.45, 1.41), (3.05, 1.36), (3.85, 1.13), (4.3, 1.03, "c"), (4.53, 0.99),
             (4.59, 0.82), (4.58, 0.45), (4.54, 0.22, "c")],
        DLO=[(1.27, 0.97), (1.92, 1.31), (3.0, 1.3), (3.72, 1.09), (1.27, 0.95)],
        B=2.42, DOORS=[1.25, 2.42, 3.3], BELT=0.97, HEAD=(0.03, 0.36, 0.64, 0.71), TAIL=(4.4, 4.59, 0.86, 0.96),
        HOOD=(0.25, 1.05), ROOF=(2.0, 3.0), DECK=4.25, CAP=3.9, WING=4, FLARE=True),
    "super": dict(  # noqa
        WHEEL=("spoke", "#c9ccd2", 7), LAMP="popup", EXH="twin",   # NSX (NA1): very low, cab-forward canopy, long rear deck, full-width tail light
        L=4.43, H=1.17, WB=2.53, FO=1.0, TD=0.63, SILL=0.16, MID=True,
        OUT=[(0.04, 0.19, "c"), (0.0, 0.33), (0.04, 0.5), (0.35, 0.62), (0.95, 0.74), (1.4, 0.84, "c"),
             (1.7, 1.02), (1.97, 1.15), (2.55, 1.17), (2.88, 1.13), (3.3, 0.99), (3.75, 0.93, "c"), (4.33, 0.9),
             (4.43, 0.84), (4.43, 0.55), (4.4, 0.23, "c")],
        DLO=[(1.47, 0.86), (1.97, 1.1), (2.82, 1.1), (3.08, 0.97), (2.95, 0.88), (1.47, 0.83)],
        B=None, DOORS=[1.5, 2.85], BELT=0.84, HEAD=(0.08, 0.42, 0.52, 0.56), TAIL=(4.4, 4.43, 0.66, 0.8),
        HOOD=(0.3, 1.3), ROOF=(2.05, 2.8), DECK=4.1, CAP=4.1,
        INTAKE=[(2.72, 0.66), (3.1, 0.72), (3.08, 0.44), (2.76, 0.42)]),
    "super2": dict(  # noqa
        WHEEL=("twin", "#2e3036", 5), LAMP="slim", EXH="quad",   # NSX (NC1) Type S: low wedge nose, flying-buttress rear, huge side scoop
        L=4.535, H=1.215, WB=2.63, FO=1.03, TD=0.68, SILL=0.14, MID=True,
        OUT=[(0.03, 0.18, "c"), (0.0, 0.32), (0.02, 0.48, "c"), (0.32, 0.62), (0.95, 0.77), (1.38, 0.87, "c"),
             (1.72, 1.06), (1.98, 1.19), (2.55, 1.215), (2.95, 1.18), (3.45, 1.02), (3.85, 0.97, "c"), (4.38, 0.98),
             (4.53, 0.93, "c"), (4.535, 0.6), (4.49, 0.22, "c")],
        DLO=[(1.46, 0.9), (1.98, 1.14), (2.9, 1.14), (3.22, 0.99), (1.46, 0.86)],
        B=None, DOORS=[1.48, 2.92], BELT=0.87, HEAD=(0.05, 0.42, 0.53, 0.58), TAIL=(4.47, 4.535, 0.83, 0.88),
        HOOD=(0.3, 1.25), ROOF=(2.05, 2.85), DECK=4.15, CAP=4.2,
        INTAKE=[(2.78, 0.82), (3.2, 0.88), (3.16, 0.4), (2.82, 0.4)]),
    "rsx": dict(  # noqa
        WHEEL=("spoke", "#c9ccd2", 5), LAMP="tall", EXH="single",   # RSX Type-S: wedge three-door, beltline kicking up, long sloping hatch with a spoiler
        L=4.37, H=1.40, WB=2.57, FO=0.94, TD=0.62, SILL=0.2,
        OUT=[(0.04, 0.23, "c"), (0.0, 0.41), (0.03, 0.62), (0.18, 0.74), (0.55, 0.82), (1.05, 0.95, "c"),
             (1.42, 1.17), (1.75, 1.37), (2.3, 1.4), (2.75, 1.36), (3.6, 1.12), (3.96, 1.04, "c"), (4.3, 0.99),
             (4.37, 0.86), (4.36, 0.46), (4.32, 0.25, "c")],
        DLO=[(1.15, 0.97), (1.75, 1.31), (2.7, 1.3), (3.45, 1.1), (3.2, 1.08), (1.15, 0.95)],
        B=2.62, DOORS=[1.13, 2.62], BELT=0.97, HEAD=(0.03, 0.38, 0.64, 0.72), TAIL=(4.15, 4.37, 0.88, 0.98),
        HOOD=(0.22, 0.95), ROOF=(1.9, 2.7), DECK=3.98, CAP=3.75, WING=2),
    "tsx": dict(  # noqa
        WHEEL=("spoke", "#c9ccd2", 7), LAMP="tall", EXH="single",   # TSX: a classic three-box sport sedan, upright glass, short high decklid
        L=4.66, H=1.455, WB=2.67, FO=0.95, TD=0.63, SILL=0.21,
        OUT=[(0.04, 0.25, "c"), (0.0, 0.43), (0.02, 0.64), (0.15, 0.78), (0.6, 0.86), (1.15, 0.98, "c"),
             (1.55, 1.22), (1.9, 1.42), (2.35, 1.455), (3.05, 1.44), (3.45, 1.3), (3.78, 1.1, "c"), (3.9, 1.06),
             (4.55, 1.04), (4.66, 0.98, "c"), (4.66, 0.8), (4.64, 0.45), (4.6, 0.27, "c")],
        DLO=[(1.27, 1.0), (1.9, 1.38), (3.04, 1.38), (3.38, 1.24), (3.62, 1.08), (1.27, 0.99)],
        B=2.45, DOORS=[1.25, 2.45, 3.4], BELT=1.0, HEAD=(0.02, 0.33, 0.68, 0.77), TAIL=(4.48, 4.66, 0.86, 0.98),
        HOOD=(0.25, 1.05), ROOF=(2.05, 3.0), DECK=4.4, CAP=3.3, C=3.3),
    "integra_s": dict(  # noqa
        WHEEL=("spoke", "#3a3d44", 10), LAMP="slim", EXH="center3",   # Integra Type S: long fastback liftback roof, wide flares, small ducktail
        L=4.73, H=1.39, WB=2.735, FO=1.0, TD=0.67, SILL=0.18,
        OUT=[(0.04, 0.21, "c"), (0.0, 0.38), (0.03, 0.6), (0.18, 0.73), (0.6, 0.82), (1.18, 0.95, "c"),
             (1.58, 1.17), (1.95, 1.35), (2.45, 1.39), (3.0, 1.36), (3.95, 1.12), (4.45, 1.03, "c"), (4.66, 1.0, "c"),
             (4.73, 0.86), (4.72, 0.45), (4.68, 0.22, "c")],
        DLO=[(1.3, 0.97), (1.95, 1.3), (3.0, 1.3), (3.82, 1.1), (3.55, 1.05), (1.3, 0.96)],
        B=2.45, DOORS=[1.28, 2.45, 3.35], BELT=0.97, HEAD=(0.03, 0.36, 0.63, 0.7), TAIL=(4.5, 4.73, 0.88, 0.97),
        HOOD=(0.25, 1.08), ROOF=(2.05, 2.95), DECK=4.45, CAP=3.9, WING=2, FLARE=True),
    "tlx": dict(  # noqa
        WHEEL=("twin", "#4a4e57", 5), LAMP="slim", EXH="quad",   # TLX Type S: long hood with a long dash-to-axle, cabin pushed back, coupe-like roof, ducktail
        L=4.94, H=1.43, WB=2.87, FO=0.95, TD=0.68, SILL=0.18,
        OUT=[(0.04, 0.21, "c"), (0.0, 0.4), (0.03, 0.63), (0.2, 0.77), (0.75, 0.86), (1.42, 1.0, "c"),
             (1.85, 1.24), (2.22, 1.4), (2.72, 1.43), (3.28, 1.4), (4.05, 1.13), (4.38, 1.05, "c"), (4.82, 1.02, "c"),
             (4.94, 0.94), (4.93, 0.45), (4.89, 0.22, "c")],
        DLO=[(1.53, 1.02), (2.22, 1.35), (3.25, 1.34), (3.95, 1.1), (1.53, 1.0)],
        B=2.78, DOORS=[1.5, 2.78, 3.65], BELT=1.01, HEAD=(0.03, 0.4, 0.67, 0.72), TAIL=(4.78, 4.94, 0.88, 0.95),
        HOOD=(0.3, 1.32), ROOF=(2.3, 3.2), DECK=4.62, CAP=4.1),
    "proto": dict(  # noqa
        LAMP="slim", EXH="none",   # endurance prototype: splitter, tall wheel fenders, bubble canopy, fin, long tail
        L=5.1, H=1.06, WB=3.15, FO=1.0, TD=0.71, SILL=0.14, MID=True, GT3=True, PROTO=True,
        OUT=[(0.0, 0.1, "c"), (0.03, 0.3), (0.3, 0.44), (0.72, 0.68), (1.0, 0.8), (1.3, 0.76), (1.7, 0.78, "c"),
             (2.05, 1.0), (2.5, 1.06), (2.92, 1.0), (3.35, 0.88), (3.85, 0.84), (4.15, 0.86), (4.55, 0.8),
             (5.02, 0.72, "c"), (5.1, 0.42), (5.08, 0.14, "c")],
        DLO=[(1.82, 0.84), (2.1, 1.0), (2.58, 1.01), (2.86, 0.92), (1.82, 0.84)],
        B=None, DOORS=[1.75, 2.85], BELT=0.84, HEAD=(0.12, 0.45, 0.42, 0.46), TAIL=(5.0, 5.1, 0.58, 0.64),
        CUTS=[(1.4, 0.76), (3.72, 0.86)],
        HOOD=None, ROOF=None, DECK=4.85, CAP=None, WING=5,
        FIN=[(2.8, 1.02), (4.55, 1.0), (4.6, 0.84), (3.35, 0.88)],
        INTAKE=[(3.05, 0.62), (3.62, 0.66), (3.6, 0.38), (3.1, 0.36)]),
}
PROFILES["super3"] = PROFILES["super2"]                               # Acura NSX: the same NC1 shape

# Visual tiers per part level (0..5)
WHEEL_STYLES = [
    ("steel", "#4a4d55", 0), ("5-spoke", "#c9ccd2", 5), ("6-spoke", "#d7d9de", 6),
    ("10-spoke forged", "#5b5f68", 10), ("6-spoke bronze", "#b0823c", 6), ("center-lock", "#c19a49", 7),
]
CALIPER = [None, "#2a2a2a", "#d62828", "#d62828", "#f4c430", "#f4c430"]


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


def _wheel(cx: float, cy: float, tires: int, brakes: int, gt3: bool, uid: str = "w", stock=None) -> str:
    style, rim, spokes = WHEEL_STYLES[min(tires, 5)]
    if stock and tires < 3 and not gt3:  # the car's own factory wheel design until you fit aftermarket ones
        style, rim, spokes = stock
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
        twin = style == "twin"
        if twin:
            w = 1.6
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r_rim}" fill="none" stroke="url(#{uid}r)" stroke-width="2.4"/>')
        angs = ([k * 360 / spokes + 18 + d for k in range(spokes) for d in (-6, 6)] if twin
                else [k * 360 / spokes + 18 for k in range(spokes)])
        for deg in angs:
            a = math.radians(deg)
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


def _scaled(p: dict, fx: float, fz: float, **over) -> dict:
    """A profile stretched in length (fx) and height (fz): for the race versions of a road car."""
    def pt(r):
        return (r[0] * fx, r[1] * fz) + tuple(r[2:])
    q = dict(p)
    for k in ("OUT", "DLO", "INTAKE", "FIN"):
        if p.get(k):
            q[k] = [pt(r) for r in p[k]]
    for k in ("HEAD", "TAIL"):
        a, b, c, d = p[k]
        q[k] = (a * fx, b * fx, c * fz, d * fz)
    for k in ("B", "DECK", "CAP", "C"):
        if p.get(k):
            q[k] = p[k] * fx
    for k in ("DOORS",):
        q[k] = [x * fx for x in p[k]]
    for k in ("HOOD", "ROOF"):
        if p.get(k):
            q[k] = (p[k][0] * fx, p[k][1] * fx)
    q["BELT"] = p["BELT"] * fz
    q.update(over)
    return q


PROFILES["gt3"] = _scaled(PROFILES["super2"], 4.64 / 4.535, 0.955, L=4.64, H=1.16, TD=0.71, SILL=0.14, GT3=True, WING=5)
PROFILES["gt3evo"] = dict(PROFILES["gt3"])
BODIES = PROFILES  # (older name, kept for callers)

K = 65.0          # SVG units per metre: every car is drawn to the same scale
CX = 178.0        # cars are centred on this x


def _geom(p: dict):
    x0 = CX - p["L"] * K / 2  # rear bumper x (front faces right)

    def P(f: float, z: float) -> tuple[float, float]:
        return x0 + (p["L"] - f) * K, GROUND - z * K
    return P


def _spline(pts: list, closed: bool = False) -> str:
    """Smooth Catmull-Rom through the points (corners marked "c" stay sharp), as SVG cubic segments."""
    out = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    n = len(pts)
    for i in range(n - 1 if not closed else n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        p0 = pts[i - 1] if (i > 0 or closed) else p1
        p3 = pts[(i + 2) % n] if (i + 2 < n or closed) else p2
        if len(p1) > 2:  # sharp corner: no tangent from behind
            p0 = p1
        if len(p2) > 2:
            p3 = p2
        t = 0.18
        c1 = (p1[0] + (p2[0] - p0[0]) * t, p1[1] + (p2[1] - p0[1]) * t)
        c2 = (p2[0] - (p3[0] - p1[0]) * t, p2[1] - (p3[1] - p1[1]) * t)
        out.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(out) + (" Z" if closed else "")


def _z_at(p: dict, f: float) -> float:
    """Height of the body's top line at f (linear between outline points)."""
    pts = [(r[0], r[1]) for r in p["OUT"]]
    top = pts[2:-2]
    best = max((z for ff, z in top if abs(ff - f) < 0.35), default=p["BELT"])
    for (a, za), (b, zb) in zip(top, top[1:]):
        if min(a, b) <= f <= max(a, b) and a != b:
            return za + (zb - za) * (f - a) / (b - a)
    return best


def car_svg(model_body: str, color: str, number, parts: dict, condition: int, width: int = 440,
            studio: bool = False) -> str:
    """Side profile drawn to scale from the car's real proportions, with paint shading, glass, lights and every
    upgrade visible. studio=True adds a showroom floor, spotlight and reflection (for the Showroom)."""
    p = PROFILES.get(model_body, PROFILES["sedan"])
    P = _geom(p)
    gt3 = bool(p.get("GT3"))
    lv = {k: min(5, int(v)) for k, v in (parts or {}).items()}
    aero, eng, tires, brakes, turbo, weight = (lv.get(k, 0) for k in ("aero", "engine", "tires", "brakes", "turbo", "weight"))
    L, FO, WB = p["L"], p["FO"], p["WB"]
    rt = p["TD"] / 2 * K + (0.8 if tires >= 3 else 0)
    arch = rt + 3.2 + (1.6 if p.get("FLARE") or gt3 else 0)
    fx, _ = P(FO, 0)
    rx, _ = P(FO + WB, 0)
    front, rear = P(0, 0)[0], P(L, 0)[0]
    sill = GROUND - p["SILL"] * K
    wy = GROUND - rt
    drop = min(5, (tires + aero) // 2 + (2 if gt3 else 0))
    num = html.escape(str(number))
    dark = "#15161a"
    u = _uid(model_body, color, str(sorted(lv.items())), condition, studio, "v2")
    hi, lo, sh = _mix(color, "#ffffff", .4), _mix(color, "#000000", .4), _mix(color, "#000000", .62)
    out_pts = [P(r[0], r[1]) + tuple(r[2:]) for r in p["OUT"]]
    top = _spline(out_pts)
    # bottom: from the rear bumper along the sill, cutting the wheel arches, back to the front bumper
    fb, rb = out_pts[0], out_pts[-1]
    bottom = (f" L{rb[0]:.1f},{sill:.1f} L{rx - arch:.1f},{sill:.1f} A{arch:.1f},{arch:.1f} 0 0 1 {rx + arch:.1f},{sill:.1f}"
              f" L{fx - arch:.1f},{sill:.1f} A{arch:.1f},{arch:.1f} 0 0 1 {fx + arch:.1f},{sill:.1f} L{fb[0]:.1f},{fb[1]:.1f} Z")
    body = top + bottom
    roof_y = GROUND - p["H"] * K
    belt_y = GROUND - p["BELT"] * K
    g = [f'<defs>'
         f'<linearGradient id="{u}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{hi}"/>'
         f'<stop offset=".42" stop-color="{color}"/><stop offset=".74" stop-color="{lo}"/><stop offset="1" stop-color="{sh}"/>'
         f'</linearGradient>'
         f'<linearGradient id="{u}g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4a5f78"/>'
         f'<stop offset=".5" stop-color="#151c26"/><stop offset="1" stop-color="#0a0d12"/></linearGradient>'
         f'<radialGradient id="{u}h" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fffbe6"/>'
         f'<stop offset=".5" stop-color="#ffe9a8" stop-opacity=".55"/><stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/>'
         f'</radialGradient>'
         f'<radialGradient id="{u}t" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ff4d4d"/>'
         f'<stop offset=".55" stop-color="#d90429" stop-opacity=".5"/><stop offset="1" stop-color="#d90429" stop-opacity="0"/>'
         f'</radialGradient><clipPath id="{u}c"><path d="{body}"/></clipPath></defs>']
    # paint, then light and shadow clipped to the body: shoulder highlight band, lower-body shadow, a soft sweep
    for wx in (rx, fx):  # wheel wells: dark inside the arch, so the tyre sits in the body instead of floating
        g.append(f'<circle cx="{wx:.1f}" cy="{wy:.1f}" r="{arch - .4:.1f}" fill="#060608"/>')
    g.append(f'<path d="{body}" fill="url(#{u}b)" stroke="#0b0c0e" stroke-width="1.3" stroke-linejoin="round"/>')
    g.append(f'<g clip-path="url(#{u}c)">'
             f'<path d="M{rear - 5},{belt_y + 6:.1f} C{rear + 90},{belt_y + 2:.1f} {front - 90},{belt_y + 2:.1f} {front + 5},{belt_y + 7:.1f} '
             f'L{front + 5},{belt_y + 11:.1f} C{front - 90},{belt_y + 6:.1f} {rear + 90},{belt_y + 6:.1f} {rear - 5},{belt_y + 10:.1f} Z" '
             f'fill="#ffffff" opacity=".17"/>'
             f'<rect x="{rear - 5}" y="{sill - 9:.1f}" width="{front - rear + 10:.1f}" height="14" fill="#000" opacity=".3"/>'
             f'<path d="M{CX + 30},{roof_y - 5:.1f} L{CX + 70},{roof_y - 5:.1f} L{CX - 40},{sill + 4:.1f} L{CX - 80},{sill + 4:.1f} Z" '
             f'fill="#ffffff" opacity=".05"/>'
             + (f'<path d="M{rx - arch - 4:.1f},{sill:.1f} Q{rx:.1f},{wy - arch - 7:.1f} {rx + arch + 4:.1f},{sill:.1f}" '
                f'fill="none" stroke="#ffffff" stroke-opacity=".14" stroke-width="2.5"/>'
                f'<path d="M{fx - arch - 4:.1f},{sill:.1f} Q{fx:.1f},{wy - arch - 7:.1f} {fx + arch + 4:.1f},{sill:.1f}" '
                f'fill="none" stroke="#ffffff" stroke-opacity=".14" stroke-width="2.5"/>' if p.get("FLARE") or gt3 else "")
             + '</g>')
    g.append(f'<path d="{top}" fill="none" stroke="#ffffff" stroke-opacity=".35" stroke-width="1.1" transform="translate(0,1.8)"/>')
    cl_y = belt_y + (sill - belt_y) * .42  # character line: a light edge over a soft shadow, front to rear
    g.append(f'<g clip-path="url(#{u}c)"><path d="M{rx + arch + 2:.1f},{cl_y + 1.5:.1f} Q{CX:.1f},{cl_y - 1.5:.1f} {fx - arch - 2:.1f},{cl_y - 3:.1f}" '
             f'stroke="#ffffff" stroke-opacity=".22" stroke-width="1" fill="none"/>'
             f'<path d="M{rx + arch + 2:.1f},{cl_y + 3:.1f} Q{CX:.1f},{cl_y:.1f} {fx - arch - 2:.1f},{cl_y - 1.5:.1f}" '
             f'stroke="#000" stroke-opacity=".22" stroke-width="1.4" fill="none"/></g>')
    for wx in (rx, fx):  # arch lip depth
        g.append(f'<path d="M{wx - arch:.1f},{sill:.1f} A{arch:.1f},{arch:.1f} 0 0 1 {wx + arch:.1f},{sill:.1f}" fill="none" '
                 f'stroke="#000" stroke-opacity=".55" stroke-width="3"/>')
    # prototype fin and side pods
    if p.get("FIN"):
        fin = _spline([P(*r[:2]) + ("c",) for r in p["FIN"]], closed=True)
        g.append(f'<path d="{fin}" fill="{lo}" stroke="#0b0c0e" stroke-width="1"/>')
    # carbon roof (weight 2+)
    if weight >= 2 and p.get("ROOF") and not p.get("OPEN"):
        (ax, ay), (bx, by) = P(p["ROOF"][0], _z_at(p, p["ROOF"][0]) - .01), P(p["ROOF"][1], _z_at(p, p["ROOF"][1]) - .01)
        g.append(f'<path d="M{ax:.1f},{ay + 1.5:.1f} L{bx:.1f},{by + 1.5:.1f}" stroke="#1d1e22" stroke-width="4" stroke-linecap="round"/>'
                 f'<path d="M{ax:.1f},{ay + 1:.1f} L{bx:.1f},{by + 1:.1f}" stroke="#ffffff" stroke-opacity=".18" stroke-width=".7" '
                 f'stroke-dasharray="2 1.4"/>')
    # glass with glare
    dlo = _spline([P(*r[:2]) + ("c",) for r in p["DLO"]], closed=True)
    g.append(f'<path d="{dlo}" fill="#0b0c0f" stroke="#0b0c0f" stroke-width="3.2" stroke-linejoin="round"/>'
             f'<path d="{dlo}" fill="url(#{u}g)" stroke="#2b2f37" stroke-width=".7"/>')
    g.append(f'<clipPath id="{u}w"><path d="{dlo}"/></clipPath><g clip-path="url(#{u}w)">'
             f'<path d="M{CX - 30},{roof_y - 4:.1f} L{CX - 12},{roof_y - 4:.1f} L{CX - 52},{belt_y + 2:.1f} L{CX - 70},{belt_y + 2:.1f} Z" fill="#ffffff" opacity=".2"/>'
             f'<path d="M{CX - 2},{roof_y - 4:.1f} L{CX + 6},{roof_y - 4:.1f} L{CX - 34},{belt_y + 2:.1f} L{CX - 42},{belt_y + 2:.1f} Z" fill="#ffffff" opacity=".1"/>'
             f'<path d="M{CX + 30},{roof_y - 4:.1f} L{CX + 64},{roof_y - 4:.1f} L{CX + 30},{belt_y + 2:.1f} L{CX - 4},{belt_y + 2:.1f} Z" fill="#9fc3e6" opacity=".08"/>'
             + (f'<rect x="{P(p["B"], 0)[0] - 2.4:.1f}" y="{roof_y - 4:.1f}" width="4.8" height="{belt_y - roof_y + 6:.1f}" fill="#0b0c0f"/>'
                if p.get("B") else "")
             + (f'<path d="M{P(p["C"], 0)[0]:.1f},{roof_y - 4:.1f} L{P(p["C"], 0)[0] + 8:.1f},{belt_y + 4:.1f} L{P(p["C"], 0)[0] + 3:.1f},{belt_y + 4:.1f} Z" fill="#0b0c0f"/>'
                if p.get("C") else "")
             + '</g>')
    # roll cage through the glass (weight 4+)
    if weight >= 4 and not p.get("OPEN"):
        a_, b_ = P(p["DOORS"][0] + .25, 0)[0], P(p["DOORS"][-1] - .1, 0)[0]
        g.append(f'<path d="M{a_:.1f},{belt_y:.1f} L{a_ - 10:.1f},{roof_y + 7:.1f} L{b_ + 8:.1f},{roof_y + 7:.1f} L{b_:.1f},{belt_y:.1f}" '
                 f'stroke="#e5e5e5" stroke-width="1.5" fill="none" opacity=".75"/>')
    if p.get("OPEN"):  # roadster: windscreen frame, seats, headrests, roll hoops behind them
        g.append(f'<path d="{dlo}" fill="none" stroke="#111318" stroke-width="2.2" stroke-linejoin="round"/>')
        h0, h1 = p["HOOPS"]
        hz = p["HOOP_Z"]
        for f_ in (h0, h1):
            x_, y_ = P(f_, hz)
            g.append(f'<path d="M{x_ - 8:.1f},{belt_y:.1f} Q{x_ - 8:.1f},{y_:.1f} {x_:.1f},{y_:.1f} Q{x_ + 8:.1f},{y_:.1f} {x_ + 8:.1f},{belt_y:.1f} Z" '
                     f'fill="#202227" stroke="#0b0c0e" stroke-width=".8"/>')
        sx, sy = P(h0 - .35, p["BELT"] + .2)
        g.append(f'<path d="M{sx - 10:.1f},{belt_y:.1f} Q{sx - 6:.1f},{sy:.1f} {sx + 6:.1f},{sy:.1f} L{sx + 8:.1f},{belt_y:.1f} Z" fill="#7a1d1d"/>')
    # door cuts, handle, mirror, fuel door, side marker
    for k_, f_ in enumerate(p["DOORS"]):
        x_ = P(f_, 0)[0]
        g.append(f'<path d="M{x_:.1f},{belt_y + 1:.1f} L{x_ + (1.5 if k_ == 0 else -1.5):.1f},{sill - 1:.1f}" stroke="#000" stroke-opacity=".45" stroke-width="1"/>'
                 f'<path d="M{x_ + 1:.1f},{belt_y + 1:.1f} L{x_ + 2.5:.1f},{sill - 1:.1f}" stroke="#fff" stroke-opacity=".1" stroke-width=".6"/>')
    for f_, z_ in p.get("CUTS", []):  # prototype: wheel fenders are separate panels standing off the tub
        x_, y_ = P(f_, z_)
        g.append(f'<path d="M{x_:.1f},{y_:.1f} Q{x_ - 3:.1f},{(y_ + sill) / 2:.1f} {x_ + 1:.1f},{sill:.1f}" stroke="#000" '
                 f'stroke-opacity=".55" stroke-width="1.4" fill="none"/><path d="M{x_ + 1.5:.1f},{y_ + 1:.1f} Q{x_ - 1.5:.1f},{(y_ + sill) / 2:.1f} '
                 f'{x_ + 2.5:.1f},{sill:.1f}" stroke="#fff" stroke-opacity=".12" stroke-width=".8" fill="none"/>')
    hx = P(p["DOORS"][1] - .25 if len(p["DOORS"]) > 1 else p["DOORS"][0] + .5, 0)[0]
    g.append(f'<rect x="{hx:.1f}" y="{belt_y + 6:.1f}" width="10" height="2.4" rx="1.2" fill="#000" opacity=".45"/>'
             f'<rect x="{hx:.1f}" y="{belt_y + 6:.1f}" width="10" height=".9" rx=".45" fill="#fff" opacity=".22"/>')
    mx, my = P(p["DOORS"][0] + .12, p["BELT"] + .05)
    g.append(f'<path d="M{mx:.1f},{my:.1f} l8,-3 q3,0 2.4,3.6 l-8,2.6 Z" fill="url(#{u}b)" stroke="#0b0c0e" stroke-width=".8"/>')
    if not p.get("PROTO"):
        g.append(f'<circle cx="{rx + arch + 9:.1f}" cy="{belt_y + 7:.1f}" r="3" fill="none" stroke="#000" stroke-opacity=".35"/>')
        g.append(f'<rect x="{fx + arch + 3:.1f}" y="{belt_y + 10:.1f}" width="6" height="2.2" rx="1" fill="#ff9f1c" opacity=".85"/>')
    if p.get("INTAKE"):
        ip = _spline([P(*r) + ("c",) for r in p["INTAKE"]], closed=True)
        g.append(f'<path d="{ip}" fill="#0c0d10"/><path d="{ip}" fill="none" stroke="#fff" stroke-opacity=".14" stroke-width=".8"/>')
        a_ = P(p["INTAKE"][0][0], 0)[0]
        b_ = P(p["INTAKE"][1][0], 0)[0]
        ty = P(0, (p["INTAKE"][0][1] + p["INTAKE"][3][1]) / 2)[1]
        for k_ in range(4):
            xx = a_ + (b_ - a_) * (k_ + 1) / 5
            g.append(f'<path d="M{xx:.1f},{ty - 5:.1f} l-3,10" stroke="#2a2c31" stroke-width="1.2"/>')
    # front intake / grille shadow and rear reflector, placed from the bumper heights
    gx, gy = P(0.02, 0.36)
    g.append(f'<path d="M{gx - 26:.1f},{gy - 3:.1f} L{gx + 1:.1f},{gy - 2:.1f} L{gx:.1f},{gy + 8:.1f} L{gx - 30:.1f},{gy + 8:.1f} Z" fill="#0c0d10" opacity=".9"/>'
             f'<path d="M{gx - 24:.1f},{gy:.1f} L{gx - 1:.1f},{gy + .5:.1f} M{gx - 26:.1f},{gy + 3:.1f} L{gx - 1:.1f},{gy + 3.5:.1f}" stroke="#3a3d44" stroke-width=".8"/>')
    ex, ey = P(L - .02, 0.42)
    g.append(f'<rect x="{ex + 1:.1f}" y="{ey:.1f}" width="7" height="2" rx="1" fill="#b3121f" opacity=".85"/>')
    # engine: hood vents → stripe → bulge → carbon hood
    if p.get("HOOD"):
        (h0x, h0y), (h1x, h1y) = P(p["HOOD"][0], _z_at(p, p["HOOD"][0])), P(p["HOOD"][1], _z_at(p, p["HOOD"][1]))
        if eng >= 2:
            mxh, myh = (h0x + h1x) / 2, (h0y + h1y) / 2
            g.append(f'<path d="M{mxh - 6:.1f},{myh + 2:.1f} l9,-1 M{mxh - 3:.1f},{myh + 4:.1f} l9,-1" stroke="{dark}" stroke-width="2"/>')
        if eng >= 4:
            g.append(f'<path d="M{h1x + 4:.1f},{h1y + 1:.1f} Q{(h0x + h1x) / 2:.1f},{min(h0y, h1y) - 5:.1f} {h0x - 6:.1f},{h0y + 1:.1f}" '
                     f'fill="none" stroke="{dark}" stroke-width="2.4"/>')
        if eng >= 5:
            g.append(f'<path d="M{h1x:.1f},{h1y + .5:.1f} L{h0x:.1f},{h0y + .5:.1f}" stroke="#202124" stroke-width="5" stroke-linecap="round"/>'
                     f'<path d="M{h1x:.1f},{h1y:.1f} L{h0x:.1f},{h0y:.1f}" stroke="#fff" stroke-opacity=".15" stroke-width=".7" stroke-dasharray="2 1.4"/>')
    if eng >= 3:
        sy_ = (belt_y + sill) / 2 + 3
        g.append(f'<g clip-path="url(#{u}c)"><path d="M{rear:.1f},{sy_:.1f} L{front:.1f},{sy_:.1f}" stroke="#fff" stroke-opacity=".9" stroke-width="3"/>'
                 f'<path d="M{rear:.1f},{sy_ + 3.4:.1f} L{front:.1f},{sy_ + 3.4:.1f}" stroke="#fff" stroke-opacity=".5" stroke-width=".8"/></g>')
    # lights with glow
    a, b, c, d = p["HEAD"]
    (hx0, hy0), (hx1, hy1) = P(b, d), P(a, c)
    hw, hh = hx1 - hx0, hy1 - hy0
    lamp = p.get("LAMP", "tall")
    if lamp == "popup":  # closed pop-up covers: a seam on the nose, plus the small lamps in the bumper
        (sx0, sy0), (sx1, sy1) = P(0.62, _z_at(p, 0.62)), P(0.12, _z_at(p, 0.12))
        g.append(f'<path d="M{sx0:.1f},{sy0 + 1:.1f} L{sx1:.1f},{sy1 + 1:.1f} L{sx1 + 1:.1f},{sy1 + 4:.1f} L{sx0:.1f},{sy0 + 3.4:.1f}" '
                 f'fill="none" stroke="#000" stroke-opacity=".5" stroke-width=".9"/>')
        hy0, hy1 = P(0, 0.4)[1], P(0, 0.35)[1]
        hx0, hx1 = P(0.32, 0)[0], P(0.02, 0)[0]
        hw, hh = hx1 - hx0, hy1 - hy0
    elif lamp == "slim":
        g.append(f'<path d="M{hx0 - 3:.1f},{hy0 + hh * .2:.1f} L{hx1:.1f},{hy0 + hh * .55:.1f}" stroke="#fff6d8" stroke-width="1.1" opacity=".9"/>')
    g.append(f'<ellipse cx="{hx1 + 2:.1f}" cy="{(hy0 + hy1) / 2:.1f}" rx="{hw * .7 + 6:.1f}" ry="{hh + 5:.1f}" fill="url(#{u}h)" opacity=".75"/>'
             f'<path d="M{hx0:.1f},{hy0 + hh * .35:.1f} L{hx1 - 1:.1f},{hy0:.1f} Q{hx1 + 1:.1f},{hy0:.1f} {hx1:.1f},{hy1 - 1:.1f} '
             f'L{hx0 + 2:.1f},{hy1:.1f} Z" fill="#eef1f5" stroke="#0b0c0e" stroke-width=".6"/>'
             f'<path d="M{hx0 + 3:.1f},{hy1 - 1.2:.1f} L{hx1 - 2:.1f},{hy1 - 1.8:.1f}" stroke="#ffffff" stroke-width="1"/>')
    a, b, c, d = p["TAIL"]
    (tx0, ty0), (tx1, ty1) = P(b, d), P(a, c)
    g.append(f'<ellipse cx="{tx0 + 2:.1f}" cy="{(ty0 + ty1) / 2:.1f}" rx="{tx1 - tx0 + 5:.1f}" ry="{ty1 - ty0 + 4:.1f}" fill="url(#{u}t)" opacity=".7"/>'
             f'<rect x="{tx0:.1f}" y="{ty0:.1f}" width="{max(3, tx1 - tx0):.1f}" height="{ty1 - ty0:.1f}" rx="1.5" fill="#c1121f" stroke="#5a0710" stroke-width=".5"/>'
             f'<rect x="{tx0 + .8:.1f}" y="{ty0 + .8:.1f}" width="{max(1.5, tx1 - tx0 - 1.6):.1f}" height="{max(1, (ty1 - ty0) * .3):.1f}" rx=".6" fill="#ff6b6b"/>')
    # number roundel on the door
    rnx = P((p["DOORS"][0] + (p["B"] or p["DOORS"][-1])) / 2 if p.get("B") else (p["DOORS"][0] + p["DOORS"][-1]) / 2, 0)[0]
    rny = (belt_y + sill) / 2 - 1
    g.append(f'<circle cx="{rnx:.1f}" cy="{rny:.1f}" r="9.5" fill="#fff" stroke="#111" stroke-width="1.2"/>'
             f'<text x="{rnx:.1f}" y="{rny + 3.8:.1f}" font-size="10.5" font-family="Arial,sans-serif" font-weight="700" '
             f'text-anchor="middle" fill="#111">{num}</text>')
    # aero: splitter → skirts → canards → diffuser → rear wing tiers (factory wing on some cars)
    fby = fb[1]
    if aero >= 1 or gt3:
        ext = 10 if (aero >= 5 or gt3) else 5
        g.append(f'<path d="M{front - 40:.1f},{fby:.1f} L{front + ext:.1f},{fby:.1f} L{front + ext - 2:.1f},{fby + 3:.1f} L{front - 40:.1f},{fby + 3:.1f} Z" fill="{dark}"/>')
    if aero >= 2 or gt3:
        g.append(f'<path d="M{rx + arch:.1f},{sill + 1:.1f} L{fx - arch:.1f},{sill + 1:.1f}" stroke="{dark}" stroke-width="4"/>')
    if aero >= 3:
        cx_, cy_ = P(0.05, 0.45)
        g.append(f'<path d="M{cx_ - 10:.1f},{cy_ - 4:.1f} l12,-2 l-2,4 Z M{cx_ - 8:.1f},{cy_ + 3:.1f} l11,-1 l-2,4 Z" fill="#1b1c20"/>')
    if aero >= 5 or gt3:
        dx_, dy_ = rb[0], rb[1]
        g.append(f'<path d="M{dx_:.1f},{dy_:.1f} L{dx_ + 30:.1f},{dy_:.1f} M{dx_ + 6:.1f},{dy_:.1f} L{dx_ + 2:.1f},{dy_ + 6:.1f} '
                 f'M{dx_ + 16:.1f},{dy_:.1f} L{dx_ + 12:.1f},{dy_ + 6:.1f} M{dx_ + 26:.1f},{dy_:.1f} L{dx_ + 22:.1f},{dy_ + 6:.1f}" '
                 f'stroke="#111" stroke-width="2.4" fill="none"/>')
    if p.get("DECK"):
        dx, dy = P(p["DECK"], _z_at(p, p["DECK"]))
        tier = max(aero, int(p.get("WING", 0)))
        if tier == 2:
            g.append(f'<path d="M{dx - 12:.1f},{dy + 1:.1f} L{dx + 14:.1f},{dy - 3:.1f} L{dx + 16:.1f},{dy + 1:.1f} Z" fill="{dark}"/>')
        elif tier == 3:
            g.append(f'<rect x="{dx - 16:.1f}" y="{dy - 11:.1f}" width="36" height="4" rx="2" fill="{dark}"/>'
                     f'<rect x="{dx - 16:.1f}" y="{dy - 11:.1f}" width="36" height="1.2" rx=".6" fill="#fff" opacity=".18"/>'
                     f'<rect x="{dx - 6:.1f}" y="{dy - 7:.1f}" width="3" height="8" fill="{dark}"/>'
                     f'<rect x="{dx + 9:.1f}" y="{dy - 7:.1f}" width="3" height="8" fill="{dark}"/>')
        elif tier >= 4:
            big = tier >= 5
            ty_ = dy - (19 if big else 15)
            span = 54 if big else 44
            x_l = dx - 26
            g.append(f'<path d="M{x_l:.1f},{ty_:.1f} L{x_l + span:.1f},{ty_ - 3:.1f} L{x_l + span:.1f},{ty_ + 2:.1f} L{x_l:.1f},{ty_ + 4:.1f} Z" '
                     f'fill="{dark}" stroke="#666" stroke-width=".6"/>'
                     f'<rect x="{x_l - 2:.1f}" y="{ty_ - 5:.1f}" width="3" height="13" fill="{dark}"/>'
                     f'<path d="M{dx - 6:.1f},{ty_ + 2:.1f} Q{dx - 10:.1f},{dy - 6:.1f} {dx:.1f},{dy:.1f}" stroke="{dark}" stroke-width="3" fill="none"/>'
                     f'<path d="M{dx + 10:.1f},{ty_ + 1:.1f} Q{dx + 6:.1f},{dy - 6:.1f} {dx + 16:.1f},{dy:.1f}" stroke="{dark}" stroke-width="3" fill="none"/>')
    # exhaust → intercooler → anti-lag flames
    ey_ = rb[1] - 7
    exh = p.get("EXH", "single")
    if exh != "none" or turbo >= 1:
        tip = 2 + turbo
        n_ = {"single": 1, "twin": 1, "quad": 2, "center3": 3}.get(exh, 1)  # side view: tips you can see
        for j in range(n_):
            yy = ey_ - j * 4.2 if exh != "center3" else ey_ - 2 + (j - 1) * 3.6
            g.append(f'<rect x="{rear - tip:.1f}" y="{yy:.1f}" width="{tip + 8:.1f}" height="{3.4 if n_ > 1 else 4.6}" rx="1.7" '
                     f'fill="#c4c7cd" stroke="#555" stroke-width=".6"/>'
                     f'<ellipse cx="{rear - tip + 1:.1f}" cy="{yy + (1.7 if n_ > 1 else 2.3):.1f}" rx="1" ry="1.4" fill="#2a2b30"/>')
    if turbo >= 3 and not p.get("MID"):
        ix_, iy_ = P(0.03, 0.34)
        g.append(f'<path d="M{ix_ - 14:.1f},{iy_:.1f} L{ix_:.1f},{iy_:.1f} L{ix_:.1f},{iy_ + 7:.1f} L{ix_ - 14:.1f},{iy_ + 7:.1f} Z" fill="#3b3f46"/>'
                 f'<path d="M{ix_ - 12:.1f},{iy_ + 2:.1f} L{ix_ - 2:.1f},{iy_ + 2:.1f} M{ix_ - 12:.1f},{iy_ + 4.5:.1f} L{ix_ - 2:.1f},{iy_ + 4.5:.1f}" stroke="#7d828c" stroke-width=".8"/>')
    if turbo >= 4:
        size = 6 + (turbo - 3) * 5
        fx0 = rear - 3 - turbo
        g.append(f'<path d="M{fx0:.1f},{ey_ + 2.3:.1f} l-{size},-3 l{size * .4},3 l-{size},3 Z" fill="#ff9f1c"/>'
                 f'<path d="M{fx0:.1f},{ey_ + 2.3:.1f} l-{size * .55},-1.5 l{size * .2},1.5 l-{size * .55},1.5 Z" fill="#ffe66d"/>')
    if weight >= 3:
        g.append(f'<path d="M{front + 1:.1f},{fby - 6:.1f} l6,0 l0,4 l-6,0" stroke="#d62828" stroke-width="2" fill="none"/>')
    if condition < 60:
        g.append(f'<path d="M{CX + 20},{belt_y + 8:.1f} l18,8 M{CX + 60},{belt_y + 6:.1f} l10,14 M{CX - 70},{belt_y + 12:.1f} l14,6" stroke="#111" stroke-width="2"/>')
    if condition < 30:
        g.append(f'<circle cx="{front - 40:.1f}" cy="{roof_y + 4:.1f}" r="9" fill="#777" opacity=".5"/>'
                 f'<circle cx="{front - 26:.1f}" cy="{roof_y - 10:.1f}" r="12" fill="#777" opacity=".35"/>')
    s_ = rt / R_TIRE
    wheels = "".join(f'<g transform="translate({wx:.1f},{wy:.1f}) scale({s_:.3f}) translate({-wx:.1f},{-wy:.1f})">'
                     f'{_wheel(wx, wy, tires, brakes, gt3, u + tag, p.get("WHEEL"))}</g>' for wx, tag in ((rx, "a"), (fx, "f")))
    car_g = f'<g transform="translate(0,{drop})">{"".join(g)}</g>{wheels}'
    shadow = (f'<ellipse cx="{CX:.1f}" cy="{GROUND + 1}" rx="{(front - rear) / 2 + 6:.1f}" ry="5" fill="#000" opacity=".45"/>'
              f'<ellipse cx="{rx:.1f}" cy="{GROUND}" rx="{rt + 5:.1f}" ry="3" fill="#000" opacity=".5"/>'
              f'<ellipse cx="{fx:.1f}" cy="{GROUND}" rx="{rt + 5:.1f}" ry="3" fill="#000" opacity=".5"/>')
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
             f'<path d="M110,-10 L250,-10 L320,{GROUND} L40,{GROUND} Z" fill="url(#{u}f)" opacity=".5"/>'
             f'<rect x="-20" y="{GROUND}" width="400" height="60" fill="#0b0c10"/>'
             f'<path d="M-20,{GROUND} L380,{GROUND}" stroke="#ffffff" stroke-opacity=".08"/>')
    reflection = f'<g mask="url(#{u}k)"><g transform="translate(0,{2 * GROUND}) scale(1,-1)">{car_g}</g></g>'
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
