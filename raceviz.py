"""
🏎️ Race replays: a little animated track, a commentary ticker, and an honest "why".
Pure functions — the app runs the race, this turns it into a replay + narration + explanation.
"""
from __future__ import annotations

import html
import json
import random

TRACK_SHAPES = {
    "Parking Lot Sprint": "M60,40 L260,40 A55,55 0 0 1 260,150 L60,150 A55,55 0 0 1 60,40 Z",
    "Bow River Circuit": "M40,95 C40,30 120,25 160,55 C200,85 230,20 280,45 C320,65 300,150 250,155 "
                         "C190,160 170,120 120,150 C70,180 40,150 40,95 Z",
    "Foothills Grand Prix": "M30,160 L270,160 C305,160 305,110 270,108 L180,104 C150,102 145,60 175,52 L270,40 "
                            "C302,36 300,12 268,12 L70,14 C25,16 15,70 40,95 C55,112 15,128 30,160 Z",
    "Rockies 6 Hours": "M50,160 C10,120 30,40 90,30 C140,22 150,70 190,60 C240,48 250,20 290,40 C320,60 300,110 "
                       "270,120 C230,135 250,170 200,172 C140,175 90,190 50,160 Z",
    "Thesis Defense Ring": "M40,40 L150,40 L170,70 L280,60 C305,58 305,100 280,110 L220,120 L240,160 L60,165 "
                           "C30,165 25,130 45,120 L90,100 L40,80 Z",
}
# What each track rewards (parts get a 30% bonus there) — and how to say it.
TRACK_CHARACTER = {
    "Parking Lot Sprint": (["tires", "brakes", "weight"], "tight, twisty and all about braking and grip"),
    "Bow River Circuit": (["aero", "tires"], "fast and flowing — grip and downforce through the sweepers"),
    "Foothills Grand Prix": (["engine", "turbo"], "long straights — straight-line speed wins it"),
    "Rockies 6 Hours": (["brakes", "weight", "engine"], "an endurance race — brakes that survive the heat and a light car"),
    "Thesis Defense Ring": (["engine", "aero", "tires"], "brutal everywhere — power, downforce and grip"),
}
RIVAL_COLORS = ["#4cc9f0", "#f72585", "#90be6d", "#f9c74f", "#b5179e", "#577590", "#f3722c"]
PASS_PHRASES = ["late on the brakes into the hairpin", "around the outside of turn 3", "with a better exit onto the straight",
                "in the slipstream down the back straight", "after a lock-up ahead", "through the fast chicane"]
LOSE_PHRASES = ["on the brakes into turn 1", "with more traction out of the hairpin", "using the slipstream",
                "after you ran wide", "around the outside — bold", "with a better run through the esses"]


def narrate(history: list[list[float]], names: list[str], you_idx: int, laps: int, track: str,
            dnf_tick: int | None, rng: random.Random) -> list[tuple[int, str]]:
    ticks = len(history)
    per_lap = max(1, ticks // laps)
    out = [(0, f"🚦 Lights out at {track}! {len(names)} cars, {laps} laps.")]

    def order(i):
        return sorted(range(len(names)), key=lambda k: history[i][k], reverse=True)

    first = order(0)
    p = first.index(you_idx) + 1
    out.append((1, f"Great launch — P{p} into turn 1!" if p <= 2 else f"Bogged the start — P{p} after turn 1."))
    prev, prev_leader, lines = first, first[0], []
    for i in range(1, ticks):
        if dnf_tick is not None and i == dnf_tick:
            out.append((i, f"💥 Lap {i // per_lap + 1}: smoke pouring from your car — it's over."))
            break
        cur = order(i)
        lap = min(laps, i // per_lap + 1)
        if cur[0] != prev_leader:
            who = "YOU take" if cur[0] == you_idx else f"{names[cur[0]]} takes"
            lines.append((i, f"Lap {lap}: {who} the lead!"))
            prev_leader = cur[0]
        a, b = prev.index(you_idx), cur.index(you_idx)
        if b < a:
            lines.append((i, f"Lap {lap}: you get past {names[cur[b + 1]]} {rng.choice(PASS_PHRASES)}."))
        elif b > a:
            lines.append((i, f"Lap {lap}: {names[cur[b - 1]]} gets by you {rng.choice(LOSE_PHRASES)}."))
        if i == ticks - per_lap:
            lines.append((i, "🏁 Final lap!"))
        prev = cur
    if len(lines) > 9:
        keep = sorted(rng.sample(range(len(lines)), 9))
        lines = [lines[k] for k in keep]
    out += lines
    if dnf_tick is None:
        fin = order(ticks - 1)
        w = "YOU" if fin[0] == you_idx else names[fin[0]]
        out.append((ticks - 1, f"🏁 {w} take{'s' if w != 'YOU' else ''} the checkered flag!"))
    return out


def explain(pos: int | str, gap: float, track: str, cond: int, heat: int, eff: dict, cap: int,
            parts_info: dict, installed, next_up) -> str:
    focus, vibe = TRACK_CHARACTER.get(track, ([], ""))
    lines = []
    if pos == "DNF":
        lines.append("**Why you DNF'd:** your car was below 40% condition — damaged cars break. Repair in the Garage first.")
    elif pos == 1:
        lines.append(f"**Why you won:** {track} is {vibe}, and your car had the pace.")
    else:
        lines.append(f"**Why P{pos}:** {track} is {vibe}. You were **{gap:.1f}s** off the win.")
    if cond < 90:
        lines.append(f"- 🔧 Condition {cond}% cost you ~{round((1 - (0.55 + 0.45 * cond / 100)) * 100)}% pace.")
    if heat:
        lines.append(f"- 🌡️ Rival heat {heat} (from missed deadlines) gave every rival +{3 * heat} pace.")
    upgradable = [k for k in focus if eff.get(k, 0) < cap]
    if upgradable:
        k = min(upgradable, key=lambda x: eff.get(x, 0))
        label, icon = parts_info[k][0], parts_info[k][1]
        nxt = next_up(k, eff.get(k, 0))
        lines.append(f"- {icon} This track rewards **{label}** — yours: *{installed(k, eff.get(k, 0))}*."
                     + (f" Next: **{nxt[0]}**." if nxt else ""))
    elif focus:
        lines.append("- 🏢 Your chassis is maxed for what this track rewards — time to move up the Honda ladder.")
    if pos not in (1, "DNF") and gap < 1.0:
        lines.append("- 🎲 Under a second — that one came down to luck. Run it back.")
    return "\n".join(lines)


def replay_html(track: str, history: list[list[float]], names: list[str], colors: list[str], you_idx: int,
                laps: int, ticker: list[tuple[int, str]], dnf_tick: int | None, seconds: float = 10) -> str:
    finish = max(max(row) for row in history) or 1
    data = {"h": [[round(d / finish, 4) for d in row] for row in history], "names": names, "colors": colors,
            "you": you_idx, "laps": laps, "ticker": ticker, "dnf": dnf_tick, "ms": int(seconds * 1000)}
    path = TRACK_SHAPES.get(track, TRACK_SHAPES["Parking Lot Sprint"])
    return f"""<div style="font-family:system-ui,sans-serif;color:#eee;background:#0d0f14;border-radius:12px;padding:8px">
<div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
<svg id="trk" viewBox="0 0 320 190" style="flex:1 1 260px;max-width:420px">
  <path d="{path}" fill="none" stroke="#2b2e36" stroke-width="16" stroke-linejoin="round"/>
  <path id="line" d="{path}" fill="none" stroke="#555a66" stroke-width="1.2" stroke-dasharray="4 5"/>
  <g id="cars"></g>
</svg>
<div style="flex:0 0 150px;font-size:12px">
  <div id="lap" style="font-weight:700;margin-bottom:4px">LAP 1/{laps}</div><ol id="board" style="margin:0;padding-left:18px"></ol>
</div></div>
<div id="tick" style="font-size:12.5px;line-height:1.45;margin-top:6px;max-height:120px;overflow:auto"></div></div>
<script>
const D={json.dumps(data)};
const line=document.getElementById('line'),L=line.getTotalLength(),g=document.getElementById('cars');
const ns='http://www.w3.org/2000/svg',dots=[];
D.names.forEach((n,i)=>{{const c=document.createElementNS(ns,'circle');c.setAttribute('r',i===D.you?6:4.2);
c.setAttribute('fill',D.colors[i]);c.setAttribute('stroke',i===D.you?'#fff':'#111');c.setAttribute('stroke-width',i===D.you?2:1);
g.appendChild(c);dots.push(c);}});
const T=D.h.length-1;let shown=0;const tk=document.getElementById('tick');
function frame(t){{const f=Math.max(0,Math.min(1,(t-st)/D.ms)),x=f*T,i=Math.floor(x),a=x-i,j=Math.min(T,i+1);
 const prog=D.names.map((_,k)=>D.h[i][k]+(D.h[j][k]-D.h[i][k])*a);
 prog.forEach((p,k)=>{{const pt=line.getPointAtLength(((p*D.laps)%1)*L);dots[k].setAttribute('cx',pt.x);dots[k].setAttribute('cy',pt.y);}});
 if(D.dnf!==null&&i>=D.dnf){{dots[D.you].setAttribute('fill','#555');}}
 const ord=prog.map((p,k)=>[p,k]).sort((u,v)=>v[0]-u[0]);
 document.getElementById('board').innerHTML=ord.map(([p,k])=>`<li style="color:${{D.colors[k]}};font-weight:${{k===D.you?800:400}}">${{D.names[k]}}</li>`).join('');
 document.getElementById('lap').textContent=f>=1?'🏁 FINISH':`LAP ${{Math.min(D.laps,Math.floor(prog[ord[0][1]]*D.laps)+1)}}/${{D.laps}}`;
 while(shown<D.ticker.length&&D.ticker[shown][0]<=x){{const d=document.createElement('div');d.textContent=D.ticker[shown][1];
  tk.prepend(d);shown++;}}
 if(f<1)requestAnimationFrame(frame);}}
const st=performance.now();requestAnimationFrame(frame);
</script>"""


def esc(s: str) -> str:
    return html.escape(s)
