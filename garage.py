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
        ("Dry-sump oiling", "Oil lives in a separate tank and a pump scavenges it from the engine, so hard cornering "
                            "can't slosh it away from the pickup — and with no deep sump the engine can sit lower."),
        ("Race engine + hybrid boost", "An electric motor fills in torque out of slow corners while the engine is still "
                                       "building revs. Energy harvested under braking gets deployed on the exit."),
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
        ("Magnesium race wheels", "Even lighter than forged aluminum. Less rotating mass means quicker acceleration "
                                  "and braking — the wheel is a flywheel you have to spin up every time."),
        ("Prototype slicks + tyre warmers", "Race tyres only grip inside a narrow temperature window. Electric "
                                           "blankets bring them up to temperature before the car leaves the pits."),
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
        ("Underbody venturi tunnels", "Shaped tunnels under the car squeeze the air and speed it up, dropping its "
                                      "pressure: ground-effect downforce with very little drag."),
        ("Prototype aero + shark fin", "The tall fin on a prototype's engine cover keeps it stable when it's sliding "
                                       "sideways, and helps stop the car from lifting off if it spins at speed."),
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
        ("Carbon-carbon discs", "Discs and pads made of carbon: they only work properly when they're very hot, "
                                "and then they stop harder and lighter than anything else."),
        ("Brake-by-wire + regen blending", "A computer splits each stop between the hybrid's regenerative braking and "
                                           "the friction brakes, so the pedal feels the same however much is being harvested."),
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
        ("Twin-scroll turbo", "Keeps the exhaust pulses from different cylinders apart on the way into the turbine, "
                              "so it spools faster with less lag."),
        ("Hot-V twin turbo", "Turbos mounted inside the V of the engine: a shorter exhaust path for quicker response "
                             "and a lower, more compact package."),
    ],
    "weight": [
        ("Light battery + rear seats out", "Less mass to accelerate, brake and turn. Power-to-weight beats raw power."),
        ("Carbon roof", "Mass up high hurts most: it raises the center of gravity and adds body roll."),
        ("Buckets + tow hooks", "Light seats that hold you in place make your inputs precise. Tow hooks: "
                                "mandatory at most tracks."),
        ("Roll cage", "Safety plus chassis stiffness — a stiff shell lets the suspension do the work."),
        ("Polycarbonate + carbon panels", "The full race diet. Every kilo removed helps everywhere at once."),
        ("Carbon tub", "A one-piece carbon-fibre safety cell: stiffer and lighter than a steel shell, and it "
                       "protects the driver in a crash."),
        ("Ballast placement", "Race cars are often built under the weight limit, then ballast is bolted in low down "
                              "exactly where the engineers want it — weight becomes a tuning tool."),
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
    # ── Acura: slotted into the ladder by real performance; the GT3 Evo22 and ARX-06 tune to L6–L7 ──
    "rsx": (3, "Its K-series engine has i-VTEC: on top of VTEC's two cam profiles, VTC continuously shifts the intake "
               "cam's timing, so you get low-rpm torque and a high-rpm rush."),
    "tsx": (3, "Double-wishbone front suspension keeps the tyre more upright as the car leans, so the contact patch "
               "stays flat on the road through a corner — rare in a family sedan."),
    "integra_s": (4, "A liftback: a sedan's profile, but the whole rear glass lifts with the hatch. The Type S shares "
                     "its turbocharged 2.0 with the Civic Type R and only comes with a manual."),
    "tlx_s": (4, "SH-AWD (Super Handling All-Wheel Drive) can send more torque to the outside rear wheel, which "
                 "pushes the car's nose into the corner instead of just adding traction."),
    "acura_nsx": (5, "A mid-engine twin-turbo V6 hybrid with three electric motors: one helping the engine, two "
                     "driving the front wheels and torque-vectoring them. Built in Ohio."),
    "nsx_evo22": (6, "An 'Evo' is a mid-life update kit the series approves: teams can't invent their own parts on a "
                     "customer GT3 car, so improvements arrive as a homologated package."),
    "crx": (3, "Under 900 kg. Light cars need less power, brake later and wear tyres less: the cheapest speed "
                "there is."),
    "s660": (3, "A kei car: Japanese rules cap engine size at 660 cc and the body's footprint, so the fun has to "
                 "come from balance. The engine sits behind the seats."),
    "prelude": (3, "ATTS (Active Torque Transfer System) shifts torque between the front wheels, an early cousin of "
                   "SH-AWD: it helps a front-drive car turn in instead of plowing wide."),
    "legend": (3, "Acura was the first Japanese luxury brand (1986); the Legend was its flagship, and its V6 sat "
                  "lengthways in a front-drive car to keep the balance even."),
    "ctr_tcr": (5, "TCR is a touring-car formula built on production cars: teams buy a homologated kit, and Balance "
                   "of Performance keeps brands even. It's where many drivers learn to race wheel-to-wheel."),
    "arx05": (7, "A DPi prototype: a shared chassis (from an approved constructor) with the maker's engine and "
                 "styling. It won three straight IMSA championships before the hybrid ARX-06 replaced it."),
    "arx06": (7, "An LMDh prototype: the chassis comes from an approved constructor and the hybrid system is a spec "
                 "part shared by every car, while the maker supplies the engine and bodywork."),
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
