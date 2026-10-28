"""
🔧 The garage: real upgrade names, what each one actually does, and per-chassis tuning limits.
Every level is a mini car lesson — read it while you spend coins you earned.
"""
from __future__ import annotations

UPGRADES = {
    "engine": [
        ("Cold-air intake + exhaust", "Lets the engine breathe: denser, cooler air in and less back-pressure out. "
                                      "Small power gain, big sound gain."),
        ("Header + ECU tune", "Re-maps fuel and ignition timing to match the new airflow. This is where most "
                              "bolt-on power actually comes from."),
        ("VTEC cams", "Honda's VTEC switches to a high-lift cam profile at high rpm — more valve lift lets in more "
                      "air, so you get power up top. Yes, it kicks in."),
        ("Individual throttle bodies", "One throttle per cylinder: razor-sharp throttle response and that intake howl."),
        ("Built motor", "Forged pistons and rods so the engine survives more rpm and boost. On its own it adds "
                        "strength, not power — it's what makes the next mod safe."),
    ],
    "tires": [
        ("Sport street tires", "Softer rubber = more grip, faster wear. Tires are the only part of the car "
                               "touching the road — the best mod per dollar."),
        ("200-treadwear track tires", "The treadwear number hints at compound hardness. Lower = stickier, "
                                      "shorter life."),
        ("Lightweight forged wheels", "Less unsprung and rotating mass: the suspension reacts faster and the "
                                      "engine spins the wheels up easier."),
        ("R-compound semi-slicks", "Almost no tread, so more rubber on the road. Needs heat to work and is "
                                   "sketchy in the rain."),
        ("Race slicks + center-lock", "Zero tread, maximum grip. A center-lock wheel has one big nut for fast "
                                      "pit stops."),
    ],
    "aero": [
        ("Front lip", "Limits how much air goes under the nose — less front lift at speed."),
        ("Side skirts + rear lip", "Seals the sides so the low-pressure air under the car stays there: "
                                   "a little downforce, a little less drag."),
        ("Canards + ducktail", "Canards (dive planes) add front downforce and spin up vortices that help seal "
                               "the floor. Aero balance front-to-rear matters as much as the total."),
        ("Swan-neck GT wing", "Mounted from above so the wing's underside — the side doing most of the work — "
                              "stays clean. Downforce = grip in fast corners, paid for with drag."),
        ("Full aero + diffuser", "The diffuser lets air under the rear expand and speed up, dropping its "
                                 "pressure — the car gets sucked to the track."),
    ],
    "brakes": [
        ("Performance pads", "Pads rated for higher temperatures so they don't fade after repeated hard stops."),
        ("Braided lines + race fluid", "Steel-braided lines don't balloon under pressure and high-boiling fluid "
                                       "avoids a soft pedal. Better feel, same stopping power."),
        ("Big brake kit", "Larger rotors give more leverage and more mass to soak up heat; multi-piston calipers "
                          "clamp the pad evenly."),
        ("Two-piece floating rotors", "Aluminum hat + iron ring: lighter, and the ring can expand with heat "
                                      "instead of warping."),
        ("Carbon-ceramic brakes", "Massive heat tolerance and very light — endurance-racing and hypercar tech."),
    ],
    "turbo": [
        ("Small turbo kit", "A turbo uses exhaust energy to spin a compressor that crams in more air. "
                            "Small turbo = quick spool, little lag."),
        ("Boost controller", "More boost pressure = more air = more power, held steady so it doesn't over-boost."),
        ("Front-mount intercooler", "Compressing air heats it, and hot air is less dense. The intercooler cools it "
                                    "back down so you keep the gains."),
        ("Bigger turbo + anti-lag", "More top-end power. Anti-lag keeps the turbo spinning off-throttle — "
                                    "that's where the pops and flames come from."),
        ("Race turbo + E85", "Ethanol resists knock and cools the intake charge, so the engine can take far "
                             "more boost."),
    ],
    "weight": [
        ("Light battery + rear seats out", "Less mass to accelerate, brake and turn. Power-to-weight beats raw power."),
        ("Carbon roof", "Mass up high hurts most: it raises the center of gravity and adds body roll."),
        ("Buckets + tow hooks", "Light seats that hold you in place make your inputs precise. Tow hooks: "
                                "mandatory at most tracks."),
        ("Roll cage", "Safety plus chassis stiffness — a stiff shell lets the suspension do the work."),
        ("Polycarbonate + carbon panels", "The full race diet. Every kilo removed helps everywhere at once."),
    ],
}

PART_INFO = {
    "engine": ("Engine", "🔥", 6), "tires": ("Wheels & tires", "🛞", 5), "aero": ("Aero", "🌀", 4),
    "brakes": ("Brakes", "🛑", 4), "turbo": ("Forced induction", "💨", 5), "weight": ("Weight reduction", "🪶", 4),
}

# How far each chassis can be tuned, plus a real fact about the car.
CHASSIS = {
    "civic_si": (3, "Si was Honda's sporty trim: a revvier engine and tighter chassis in an everyday car — the classic "
                    "first Honda build."),
    "integra_r": (4, "Often called one of the best-handling front-wheel-drive cars ever made; Honda hand-finished "
                     "parts of its engine."),
    "s2000": (4, "Its 2.0-litre four revved to 9,000 rpm and made around 120 hp per litre — no turbo. Front-mid "
                 "engine and rear-wheel drive for near 50/50 balance."),
    "ctr": (4, "Turbocharged front-wheel drive with a limited-slip differential, which keeps the inside wheel from "
               "spinning out of corners."),
    "nsx": (5, "Mid-engine with an all-aluminum body — rare for a road car in its day. Ayrton Senna gave feedback "
               "during development."),
    "nsx_s": (5, "A hybrid: twin-turbo V6 in the middle plus electric motors driving the front wheels, so it can "
                 "pull itself out of corners."),
    "nsx_gt3": (5, "A customer race car. GT3 series use Balance of Performance — weight and power tweaks so very "
                   "different cars can race wheel-to-wheel."),
}


def cap(model_id: str) -> int:
    return CHASSIS.get(model_id, (3, ""))[0]


def effective(parts: dict, model_id: str) -> dict:
    c = cap(model_id)
    return {k: min(int(parts.get(k, 0)), c) for k in PART_INFO}


def next_upgrade(part: str, level: int) -> tuple[str, str] | None:
    lst = UPGRADES[part]
    return lst[level] if level < len(lst) else None


def installed(part: str, level: int) -> str:
    return "Stock" if level == 0 else UPGRADES[part][level - 1][0]
