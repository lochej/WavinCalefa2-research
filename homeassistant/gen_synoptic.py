"""Generate the Calefa II V ITC synoptic SVG + Home Assistant card YAML.

Topology follows the installer guide ("Principdiagram, Calefa II V ITC"):
  * district supply -> DHW exchanger 01 -> T6 -> PICV 37 -> district return
  * district supply -> heating exchanger 02 -> T1 -> PICV 22 -> district return
  * cold water -> flowmeter 36 -> T3 -> exchanger 01 -> T4 -> hot water out
  * heating return -> pump 40 -> pressure 54 -> exchanger 02 -> T2 -> heating flow

Usage (from the project root):  python3 homeassistant/gen_synoptic.py homeassistant [preview.html] [--card]
  --card also rewrites calefa_card.yaml (overwrites manual tweaks).
Canvas 1000x600; overlay positions in canvas px, converted to % for picture-elements.
"""
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
PREFIX = "basement_wavin_calefa"

HOT = "#ef4444"      # district supply
HOTW = "#f97316"     # domestic hot water
HEAT = "#f59e0b"     # heating flow (secondary)
COLD = "#38bdf8"     # cold water
RET = "#3b82f6"      # district return
HRET = "#818cf8"     # heating return (secondary)
TXT = "#cbd5e1"
DIM = "#94a3b8"
BOX = "#334155"
BG = "#1e293b"

# (entity, x, y, border colour, prefix)
# (entity suffix, left %, top %, prefix) – positions as tuned in the dashboard
LABELS = [
    ("sensor", "district_supply_temperature", 20.0, 66.0, ""),        # T5
    ("sensor", "hot_water_primary_return", 56.0, 14.0, ""),           # T6
    ("sensor", "hot_water_temperature", 32.0, 34.0, ""),              # T4
    ("number", "hot_water_setpoint", 11.0, 34.0, "set "),
    ("sensor", "cold_water_temperature", 32.0, 14.3, ""),             # T3
    ("sensor", "hot_water_flow", 20.0, 24.2, ""),                     # flowmeter 36
    ("sensor", "hot_water_power", 32.0, 24.2, ""),
    ("sensor", "heating_primary_return", 68.0, 95.0, ""),             # T1
    ("sensor", "heating_valve", 67.0, 78.0, ""),                      # valve 22
    ("sensor", "hot_water_valve", 70.0, 50.0, ""),                    # valve 37
    ("sensor", "heating_supply_temperature", 91.8, 66.3, ""),         # T2
    ("sensor", "heating_flow_target", 90.5, 56.3, "target "),
    ("number", "room_setpoint", 90.5, 50.3, "room "),
    ("sensor", "heating_circuit_pressure", 80.5, 96.0, ""),           # 54
    ("sensor", "outdoor_temperature", 89.0, 15.0, ""),                # 65
    ("sensor", "district_return_estimated", 20.0, 84.3, "≈ "),
]
SAMPLE = ["68,9 °C", "38,8 °C", "36,1 °C", "set 50 °C", "39,0 °C", "0 L/h", "0,0 kW",
          "35,5 °C", "25,7%", "0,0%", "42,7 °C", "target 44,3 °C", "room 23,0 °C", "1,40 bar", "6,4 °C",
          "≈ 35,5 °C"]


def arrow(x, y, d, c):
    s = 9
    pts = {"r": f"{x-s},{y-s} {x+s},{y} {x-s},{y+s}", "l": f"{x+s},{y-s} {x-s},{y} {x+s},{y+s}",
           "d": f"{x-s},{y-s} {x},{y+s} {x+s},{y-s}", "u": f"{x-s},{y+s} {x},{y-s} {x+s},{y+s}"}[d]
    return f'<polygon points="{pts}" fill="{c}" stroke="{BG}" stroke-width="1.5"/>'


def text(x, y, s, size=14, anchor="start", fill=TXT, weight="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" '
            f'font-weight="{weight}">{s}</text>')


def pipe(d, c):
    return (f'<path d="{d}" fill="none" stroke="{c}" stroke-width="9" '
            'stroke-linecap="round" stroke-linejoin="round"/>')


def valve(x, y, vertical=False):
    """Motorised valve (PICV + actuator)."""
    if vertical:
        return ('<g stroke="#e2e8f0" stroke-width="2">'
                f'<line x1="{x}" y1="{y}" x2="{x+24}" y2="{y}"/>'
                f'<rect x="{x+24}" y="{y-13}" width="14" height="26" rx="3" fill="{BOX}"/>'
                f'<polygon points="{x-14},{y-17} {x},{y} {x+14},{y-17}" fill="{BOX}"/>'
                f'<polygon points="{x-14},{y+17} {x},{y} {x+14},{y+17}" fill="{BOX}"/></g>')
    return ('<g stroke="#e2e8f0" stroke-width="2">'
            f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y-24}"/>'
            f'<rect x="{x-13}" y="{y-38}" width="26" height="14" rx="3" fill="{BOX}"/>'
            f'<polygon points="{x-17},{y-14} {x},{y} {x-17},{y+14}" fill="{BOX}"/>'
            f'<polygon points="{x+17},{y-14} {x},{y} {x+17},{y+14}" fill="{BOX}"/></g>')


def hex_exchanger(x, y, w, h, title, tag):
    zig = " ".join(f"{x + 20 if i % 2 == 0 else x + w - 20},{y + 14 + i * (h - 28) / 10:.0f}" for i in range(11))
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{BOX}" stroke="{DIM}" stroke-width="2"/>'
            f'<polyline points="{zig}" fill="none" stroke="{DIM}" stroke-width="2.5" stroke-linejoin="round"/>'
            + text(x + w / 2, y - 14, title, 19, "middle", TXT, "600")
            + text(x + w - 8, y + h - 8, tag, 15, "end", DIM))


def bridge(x, y, vertical_colour):
    """Vertical pipe crossing a horizontal one without joining."""
    return (f'<path d="M{x} {y-22} V{y+22}" stroke="{BG}" stroke-width="19"/>'
            + pipe(f"M{x} {y-28} V{y+28}", vertical_colour))


def svg(preview=False):
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600" width="1000" height="600" '
         'font-family="Segoe UI, Roboto, Helvetica, Arial, sans-serif">',
         f'<rect width="1000" height="600" rx="18" fill="{BG}"/>']

    # ---- district (primary) side
    p.append(pipe("M760 530 H40", RET))                    # heating HEX primary out -> district return
    p.append(pipe("M40 420 H760", HOT))                    # district supply -> heating HEX
    p.append(pipe("M540 420 V230 H490", HOT))              # branch -> DHW HEX primary in (bottom right)
    p.append(pipe("M490 110 H600 V530", RET))              # DHW HEX primary out -> T6 -> PICV 37 -> return
    p.append(bridge(600, 420, RET))

    # ---- domestic water (secondary of 01)
    p.append(pipe("M40 110 H400", COLD))                   # cold water in (top left)
    p.append(pipe("M400 230 H40", HOTW))                   # hot water out (bottom left)

    # ---- heating circuit (secondary of 02)
    p.append(pipe("M850 420 H960", HEAT))                  # heating flow out
    p.append(pipe("M960 530 H850", HRET))                  # heating return in

    # arrows
    p += [arrow(100, 110, "r", COLD), arrow(80, 230, "l", HOTW),
          arrow(100, 420, "r", HOT), arrow(540, 330, "u", HOT), arrow(700, 420, "r", HOT),
          arrow(600, 200, "d", RET), arrow(600, 480, "d", RET), arrow(480, 530, "l", RET), arrow(100, 530, "l", RET),
          arrow(940, 420, "r", HEAT), arrow(980 - 15, 530, "l", HRET)]

    # components
    p.append(hex_exchanger(400, 80, 90, 180, "Hot water exchanger", "01"))
    p.append(hex_exchanger(760, 395, 90, 160, "Heating exchanger", "02"))
    p.append(valve(600, 300, vertical=True))               # PICV 37 + stepper 34 (DHW)
    p.append(valve(660, 530))                              # PICV 22 + motor 34 (heating)
    # flowmeter 36 on cold water
    p.append(f'<rect x="186" y="97" width="28" height="26" rx="4" fill="{BOX}" stroke="#e2e8f0" stroke-width="2"/>')
    p.append('<polygon points="194,103 208,110 194,117" fill="#e2e8f0"/>')
    # pump 40 on heating return (flow towards the exchanger, i.e. leftwards)
    p.append(f'<circle cx="930" cy="530" r="17" fill="{BOX}" stroke="#e2e8f0" stroke-width="2"/>')
    p.append('<polygon points="937,520 919,530 937,540" fill="#e2e8f0"/>')
    # pressure transmitter 54 on heating return
    p.append(f'<line x1="885" y1="530" x2="885" y2="553" stroke="{DIM}" stroke-width="3"/>')
    p.append(f'<circle cx="885" cy="567" r="15" fill="{BOX}" stroke="#e2e8f0" stroke-width="2"/>')
    p.append('<line x1="885" y1="567" x2="894" y2="559" stroke="#e2e8f0" stroke-width="2.5" stroke-linecap="round"/>')
    # wireless outdoor sensor 65
    p.append(f'<rect x="868" y="32" width="20" height="28" rx="3" fill="{BOX}" stroke="{DIM}" stroke-width="2"/>')
    p.append(f'<line x1="878" y1="38" x2="878" y2="54" stroke="{DIM}" stroke-width="2"/>')

    # captions
    p.append(text(40, 92, "Cold water in", 20, "start", DIM))
    p.append(text(40, 262, "Hot water out", 20, "start", DIM))
    p.append(text(40, 450, "District supply", 20, "start", DIM))
    p.append(text(40, 562, "District return", 20, "start", DIM))
    p.append(text(985, 452, "To radiators", 20, "end", DIM))
    p.append(text(985, 506, "From radiators", 20, "end", DIM))
    p.append(text(858, 54, "Outdoor", 20, "end", DIM))
    p.append(text(40, 48, "Calefa II V ITC", 24, "start", TXT, "700"))

    if preview:  # mimic the dashboard labels (white, bold, ~14px on a ~500px wide card)
        for (_, _, lx, ty, _), v in zip(LABELS, SAMPLE):
            p.append(text(lx * 10, ty * 6 + 10, v, 28, "middle", "#ffffff", "700"))
    p.append("</svg>")
    return "\n".join(p)


def card_yaml():
    out = ["type: vertical-stack", "cards:", "  - type: picture-elements",
           "    image: /local/calefa_synoptic.svg", "    elements:"]
    for dom, ent, lx, ty, pre in LABELS:
        out += ["      - type: state-label", f"        entity: {dom}.{PREFIX}_{ent}"]
        if pre:
            out.append(f'        prefix: "{pre}"')
        out += ["        style:",
                f"          left: {lx}%",
                f"          top: {ty}%",
                "          color: white",
                "          font-size: clamp(9px, 1.35vw, 14px)",
                "          font-weight: 600",
                "          white-space: nowrap"]
    out += ["      - type: conditional",
            "        conditions:",
            f"          - entity: binary_sensor.{PREFIX}_hot_water_in_use",
            '            state: "on"',
            "        elements:",
            "          - type: icon",
            "            icon: mdi:water",
            "            style:",
            "              left: 33.5%",
            "              top: 34.3%",
            f'              color: "{HOTW}"',
            '              "--mdc-icon-size": 28px',
            "  - type: history-graph",
            "    title: Hot water",
            "    hours_to_show: 24",
            "    entities:",
            f"      - entity: sensor.{PREFIX}_district_supply_temperature",
            "        name: District supply (T5)",
            f"      - entity: sensor.{PREFIX}_hot_water_primary_return",
            "        name: Hot water primary return (T6)",
            f"      - entity: sensor.{PREFIX}_district_return_estimated",
            "        name: District return (estimated)",
            f"      - entity: sensor.{PREFIX}_hot_water_temperature",
            "        name: Hot water (T4)",
            f"      - entity: sensor.{PREFIX}_cold_water_temperature",
            "        name: Cold water (T3)",
            "  - type: history-graph",
            "    title: Heating",
            "    hours_to_show: 24",
            "    entities:",
            f"      - entity: sensor.{PREFIX}_heating_supply_temperature",
            "        name: Heating flow (T2)",
            f"      - entity: sensor.{PREFIX}_heating_flow_target",
            "        name: Flow target",
            f"      - entity: sensor.{PREFIX}_heating_primary_return",
            "        name: Heating primary return (T1)",
            f"      - entity: sensor.{PREFIX}_outdoor_temperature",
            "        name: Outdoor"]
    return "\n".join(out) + "\n"


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "calefa_synoptic.svg").write_text(svg())
if "--card" in sys.argv:  # opt-in: would overwrite a hand-tuned calefa_card.yaml
    (OUT / "calefa_card.yaml").write_text(card_yaml())
prev = [a for a in sys.argv[2:] if a.endswith(".html")]
if prev:
    Path(prev[0]).write_text(f"<html><body style='margin:0;background:#888'>{svg(True)}</body></html>")
