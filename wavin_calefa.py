#!/usr/bin/env python3
"""Poll a Wavin Calefa II (DHW 212 V ITC) over Modbus RTU (RJ-M port).

Modes
  (default)      read everything once and print decoded values
  --json         same, as JSON
  --raw          dump every valid register (all tables) as raw values
  --watch SEC    poll all valid registers every SEC seconds and print only
                 the ones that changed (use this to identify unknown registers,
                 e.g. while opening a hot water tap)
  --csv FILE     with --watch: also append every raw sample to a CSV file

Addresses are raw 0-based Modbus PDU addresses (exactly what goes on the wire).
Names ending in '?' are educated guesses that still need confirmation.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field

from modbus_rtu import ModbusError, ModbusRTU, regs_to_string, to_signed

# --------------------------------------------------------------------------
# Valid address ranges found by scan.py (any read touching an address outside
# these ranges is rejected by the device with exception 2).
VALID = {
    "holding": [(3, 43), (50, 50), (6501, 6519), (6521, 6538), (7301, 7306), (7501, 7525),
                (7701, 7724), (10001, 10041), (10046, 10046), (10050, 10061), (10063, 10190)],
    "input": [(1, 2), (10, 27), (6502, 6515), (7301, 7310), (7501, 7511), (7701, 7724),
              (10001, 10011), (10017, 10728), (12801, 12807),
              (12901, 12904), (12911, 12914), (12921, 12924), (12931, 12934),
              (12941, 12944), (12951, 12954), (12961, 12964)],
    "discrete": [(1, 5), (6503, 6517), (7301, 7302), (7304, 7310), (7501, 7512), (7701, 7706)],
}
FC = {"holding": 3, "input": 4, "discrete": 2}
MAX_BLOCK = {"holding": 100, "input": 100, "discrete": 800}

INVALID_TEMP = 32767  # 0x7FFF = sensor missing / value not available

ENUMS = {
    "modbus_mode": {0: "DISABLED", 1: "READ_ONLY", 2: "READ_WRITE", 3: "WRITE_WITH_PASSWORD"},
    "onoff": {0: "OFF", 1: "ON"},
    "dhw_mode": {0: "SCHEDULE", 1: "SCHEDULE_ADAPTIVE", 2: "ECO", 3: "COMFORT"},
    "dhw_state": {1: "TAPPING", 2: "IDLE", 3: "BYPASS?", 4: "BLOCKED?", 5: "BLOCKED_BYPASS?"},  # differs from Sentio doc
    "hc_state": {1: "IDLE", 2: "HEATING", 3: "COOLING", 4: "BLOCKED_HEATING", 5: "BLOCKED_COOLING"},
    "circ_state": {0: "NONE", 1: "IDLE", 2: "ON"},
    "blocking": {0: "NONE", 1: "UNKNOWN", 2: "CONTACT", 3: "FLOOR_TEMP", 4: "LOW_ENERGY",
                 5: "AIR_TEMP", 6: "DEW_POINT", 7: "OUTDOOR_TEMP", 8: "FAULT", 9: "FAULT_HTCO",
                 10: "PERIODIC_ACTIVATION"},
    "dev_type": {1: "CCU-208", 2: "DHW-201 (Calefa)", 3: "DHW-212 (Calefa II)?"},
}


@dataclass
class Reg:
    table: str        # holding | input | discrete
    addr: int
    key: str
    desc: str
    kind: str = "u16"  # u16 s16 temp u32 str bool enum
    length: int = 1
    unit: str = ""
    enum: str | None = None
    scale: float = 1.0
    writable: bool = field(default=False)


T = "temp"
REGS: list[Reg] = [
    # ---------------- LOCATION (device / modbus config) -------------------
    Reg("input", 1, "addr_space_major", "Address space major version"),
    Reg("input", 2, "addr_space_minor", "Address space minor version"),
    Reg("input", 10, "dev_type", "Device type", "enum", enum="dev_type"),
    Reg("input", 11, "hw_version", "HW version"),
    Reg("input", 12, "sw_version", "SW version major"),
    Reg("input", 13, "sw_version_minor", "SW version minor"),
    Reg("input", 14, "serial_prefix", "Serial number prefix"),
    Reg("input", 15, "serial", "Serial number", "u32", 2),
    Reg("input", 19, "loc_temp_19", "Location IR19 (=IR10008) temp?", T, unit="°C"),
    Reg("input", 20, "outdoor_temp", "Outdoor temperature", T, unit="°C"),
    Reg("input", 21, "outdoor_temp_filtered", "Outdoor temperature filtered", T, unit="°C"),
    Reg("input", 22, "outdoor_temp_avg", "Outdoor temperature averaged", T, unit="°C"),
    Reg("input", 27, "uptime_min_res", "Uptime (s, updated every minute)", unit="s"),
    Reg("input", 10010, "temp_10010", "Temp IR10010 (board/room?)", T, unit="°C"),
    Reg("input", 10666, "boot_time", "Boot time (local-time epoch)", "u32", 2),
    Reg("input", 10727, "uptime_s", "Uptime counter", unit="s"),

    Reg("holding", 3, "modbus_address", "Modbus slave address", writable=True),
    Reg("holding", 4, "modbus_baudrate", "Modbus baudrate", "u32", 2, writable=True),
    Reg("holding", 6, "modbus_mode", "Modbus mode", "enum", enum="modbus_mode", writable=True),
    Reg("holding", 7, "modbus_parity", "Modbus parity (0=none)", writable=True),
    Reg("holding", 8, "modbus_stopbits", "Modbus stop bits (0=1 stop bit)", writable=True),
    Reg("holding", 10, "location_name", "Location name", "str", 16, writable=True),
    Reg("holding", 26, "standby", "Standby", "enum", enum="onoff", writable=True),
    Reg("holding", 27, "vacation", "Vacation", "enum", enum="onoff", writable=True),
    Reg("holding", 28, "unix_time", "Device clock (epoch, LOCAL time)", "u32", 2),
    Reg("holding", 32, "tz_offset", "Timezone offset (UTC+1 = 3600)", "s16", unit="s"),
    Reg("holding", 33, "dst", "DST flag/offset?"),

    # ---------------- DHW (domestic hot water) ----------------------------
    Reg("holding", 6501, "dhw_name", "DHW name", "str", 16, writable=True),
    Reg("holding", 6517, "dhw_mode", "DHW mode", "enum", enum="dhw_mode", writable=True),
    Reg("holding", 6518, "dhw_ui_access_level", "Display access level (<40 user, >=40 installer)", writable=True),
    Reg("holding", 6519, "dhw_block_request", "DHW block request", "enum", enum="onoff", writable=True),
    Reg("holding", 6521, "dhw_setpoint", "DHW temperature setpoint", T, unit="°C", writable=True),
    Reg("holding", 6522, "dhw_bypass_temp", "DHW bypass temperature", T, unit="°C", writable=True),
    Reg("holding", 6523, "dhw_circ_pump_present", "Circulation pump present", "enum", enum="onoff", writable=True),
    Reg("holding", 6524, "dhw_circ_inlet_temp", "Circulation inlet temperature", T, unit="°C", writable=True),

    Reg("input", 6502, "dhw_state", "DHW state", "enum", enum="dhw_state"),
    Reg("input", 6503, "dhw_blocking_source", "DHW blocking source", "enum", enum="blocking"),
    Reg("input", 6504, "dhw_circ_state", "Circulation state", "enum", enum="circ_state"),
    Reg("input", 6505, "dhw_temp", "DHW outlet temperature (=T4)", T, unit="°C"),
    Reg("input", 6506, "primary_supply_temp", "Primary (district heating) supply temp (=T5)", T, unit="°C"),
    Reg("input", 6507, "primary_return_temp", "Primary (district heating) return temp (=T6)", T, unit="°C"),
    Reg("input", 6508, "dhw_ir6508", "DHW IR6508 ?"),
    Reg("input", 6509, "cold_water_temp", "Cold water inlet temperature (=T3)", T, unit="°C"),
    Reg("input", 6510, "dhw_flow", "DHW flow (filtered)", unit="l/h"),
    Reg("input", 10671, "dhw_flow_raw", "DHW flow (unfiltered?)", unit="l/h"),
    Reg("input", 6511, "dhw_valve_position", "DHW valve position? (follows HR6529)", scale=0.01, unit="%?"),
    Reg("holding", 6529, "dhw_valve_command", "DHW valve command?", scale=0.01, unit="%?"),
    Reg("holding", 10041, "dhw_regulator_phase", "DHW regulator phase? (8 idle, 3/5 tapping)"),
    Reg("input", 6512, "dhw_ir6512", "DHW IR6512 ?"),
    Reg("input", 6513, "dhw_phase", "DHW phase? (4 idle, 2/3 tapping)"),
    Reg("input", 6514, "dhw_ir6514", "DHW IR6514 (flow/valve?)", scale=0.01),
    Reg("input", 6515, "dhw_ir6515", "DHW IR6515 ?"),

    # ---------------- 73xx (outdoor / room sensor object?) -----------------
    Reg("input", 7301, "itc_active", "ITC heating active?"),
    Reg("input", 7303, "o73_ir7303", "IR7303 ?"),
    Reg("input", 7304, "itc_valve_7304", "ITC valve/demand (=IR7706)?", scale=0.01, unit="%"),
    Reg("input", 7306, "o73_temp_7306", "Temp 7306 (outdoor?)", T, unit="°C"),
    Reg("input", 7310, "o73_ir7310", "IR7310 ?", scale=0.01),

    # ---------------- 75xx room temperature presets ------------------------
    Reg("holding", 7501, "room_setpoint", "Room setpoint (currently selected)", T, unit="°C", writable=True),
    Reg("holding", 7502, "room_preset_eco", "Room preset ECO", T, unit="°C", writable=True),
    Reg("holding", 7503, "room_preset_comfort", "Room preset COMFORT", T, unit="°C", writable=True),
    Reg("holding", 7504, "room_preset_extra_comfort", "Room preset EXTRA COMFORT", T, unit="°C", writable=True),
    Reg("input", 7501, "room_state", "Room state?", "enum", enum="hc_state"),
    Reg("input", 7510, "room_desired_temp", "Room desired temperature (follows HR7501)", T, unit="°C"),
    Reg("input", 7511, "room_desired_temp_2", "Room desired temperature (2)?", T, unit="°C"),

    # ---------------- 77xx heating circuit (ITC) ---------------------------
    Reg("input", 7701, "heating_supply_temp", "Heating flow (supply) temp (=T2)", T, unit="°C"),
    Reg("input", 7702, "heating_return_temp", "Heating return temp (=T1)", T, unit="°C"),
    Reg("input", 7703, "heating_supply_target", "Heating flow target (heat curve)", T, unit="°C"),
    Reg("input", 7704, "itc_ir7704", "ITC IR7704 (pump demand?)"),
    Reg("input", 7705, "itc_ir7705", "ITC IR7705 (pump state?)"),
    Reg("input", 7706, "itc_valve", "ITC valve opening/demand?", scale=0.01, unit="%"),

    # ---------------- discrete inputs (alarms) -----------------------------
    Reg("discrete", 1, "alarm_location_warning", "Location aggregated warning", "bool"),
    Reg("discrete", 2, "alarm_location_error", "Location aggregated error", "bool"),
    *[Reg("discrete", a, f"di_{a}", f"DI{a} ?", "bool") for a in (3, 4, 5)],
    Reg("discrete", 6503, "alarm_dhw_low_energy", "DHW warning: retentive low energy?", "bool"),
    Reg("discrete", 6504, "alarm_dhw_temp_high", "DHW error: DHW temp high?", "bool"),
    Reg("discrete", 6505, "alarm_dhw_motor", "DHW error: motor failure?", "bool"),
    Reg("discrete", 6506, "alarm_dhi_sensor", "DHW error: DHI sensor (primary inlet)?", "bool"),
    Reg("discrete", 6507, "alarm_dho_sensor", "DHW error: DHO sensor (primary return)?", "bool"),
    Reg("discrete", 6508, "alarm_dhw_sensor", "DHW error: DHW sensor?", "bool"),
    Reg("discrete", 6509, "alarm_dcw_sensor", "DHW error: DCW sensor (cold water)?", "bool"),
    *[Reg("discrete", a, f"di_{a}", f"DI{a} ?", "bool") for a in range(6510, 6518)],
    *[Reg("discrete", a, f"di_{a}", f"DI{a} ?", "bool") for a in (7301, 7302, *range(7304, 7311))],
    *[Reg("discrete", a, f"di_{a}", f"DI{a} ?", "bool") for a in range(7501, 7513)],
    Reg("discrete", 7701, "alarm_itc_warning", "ITC aggregated warning?", "bool"),
    Reg("discrete", 7702, "alarm_itc_error", "ITC aggregated error?", "bool"),
    Reg("discrete", 7703, "alarm_itc_inlet_sensor", "ITC error: inlet sensor failure?", "bool"),
    Reg("discrete", 7704, "alarm_itc_htco", "ITC error: high temp cut-off?", "bool"),
    *[Reg("discrete", a, f"di_{a}", f"DI{a} ?", "bool") for a in (7705, 7706)],

    Reg("holding", 7701, "heat_curve_slope", "Heat curve slope", scale=0.1, writable=True),
    Reg("holding", 7703, "heat_curve_slope_2", "Heat curve slope (2nd copy/active?)", scale=0.1, writable=True),
    Reg("holding", 7706, "heat_curve_min", "Heat curve min flow temperature", T, unit="°C", writable=True),
    Reg("holding", 7707, "heat_curve_max", "Heat curve max flow temperature", T, unit="°C", writable=True),
    Reg("holding", 7708, "itc_p_gain", "ITC regulator P gain", scale=0.1, writable=True),
    Reg("holding", 7709, "itc_i_time", "ITC regulator I time", writable=True),
    Reg("holding", 7713, "return_limiter_mode", "Return limiter mode (2 = maximum?)", writable=True),
    Reg("holding", 7716, "return_limit_max", "Return limiter maximum temperature", T, unit="°C", writable=True),
    Reg("holding", 7717, "return_limit_max_gain", "Return limiter gain at max limit", "s16", scale=0.1, writable=True),
    Reg("holding", 7718, "return_limit_priority", "Return limiter priority over flow temp", "enum", enum="onoff", writable=True),
    Reg("holding", 7302, "itc_valve_hr", "ITC valve/demand (mirror of IR7706)", scale=0.01, unit="%"),

    # ---------------- 128xx raw hardware sensor inputs ---------------------
    *[Reg("input", 12800 + i, f"sensor_t{i}", f"Thermistor input T{i}", T, unit="°C") for i in range(1, 8)],
    *[Reg("input", 12891 + 10 * i + 1, f"sensor_t{i}_raw", f"T{i} raw (ADC/resistance?)") for i in range(1, 8)],
    *[Reg("input", 12891 + 10 * i + 2, f"sensor_t{i}_status", f"T{i} status word?", "u16") for i in range(1, 8)],
    *[Reg("input", 12891 + 10 * i + 3, f"sensor_t{i}_offset", f"T{i} offset/correction?", "s16") for i in range(1, 8)],
]


# --------------------------------------------------------------------------
def read_table(m: ModbusRTU, table: str) -> dict[int, int]:
    out: dict[int, int] = {}
    for start, end in VALID[table]:
        a = start
        while a <= end:
            n = min(MAX_BLOCK[table], end - a + 1)
            for attempt in range(3):
                try:
                    if table == "discrete":
                        vals = [int(b) for b in m.read_discrete(a, n)]
                    else:
                        vals = m.read_registers(FC[table], a, n)
                    break
                except ModbusError as e:
                    if attempt == 2:
                        print(f"read {table} {a}+{n} failed: {e}", file=sys.stderr)
                        vals = None
                    time.sleep(0.1)
            if vals:
                out.update({a + i: v for i, v in enumerate(vals)})
            a += n
    return out


def read_all(m: ModbusRTU) -> dict[str, dict[int, int]]:
    return {t: read_table(m, t) for t in VALID}


def decode(reg: Reg, raw: dict[str, dict[int, int]]):
    tbl = raw[reg.table]
    words = [tbl.get(reg.addr + i) for i in range(reg.length)]
    if any(w is None for w in words):
        return None
    w = words[0]
    if reg.kind == "temp":
        return None if w == INVALID_TEMP else round(to_signed(w) / 100, 2)
    if reg.kind == "s16":
        return to_signed(w) * reg.scale if reg.scale != 1 else to_signed(w)
    if reg.kind == "u32":
        return (words[0] << 16) | words[1]
    if reg.kind == "str":
        return regs_to_string(words)
    if reg.kind == "enum":
        return ENUMS[reg.enum].get(w, f"UNKNOWN({w})")
    if reg.kind == "bool":
        return bool(w)
    return round(w * reg.scale, 2) if reg.scale != 1 else w


def decoded(raw) -> dict:
    return {r.key: decode(r, raw) for r in REGS}


def print_decoded(raw):
    cur = None
    for r in REGS:
        v = decode(r, raw)
        if r.key == "unix_time" and v:
            v = f"{v}  ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(v))})"
        tag = {"holding": "HR", "input": "IR", "discrete": "DI"}[r.table]
        if r.table != cur:
            cur = r.table
        unit = r.unit if v is not None else ""
        print(f"{tag}{r.addr:<6} {'RW' if r.writable else 'R '} {r.desc:<52} {v} {unit}")


def print_raw(raw):
    for t, vals in raw.items():
        print(f"== {t}")
        for a, v in vals.items():
            s = to_signed(v)
            extra = f"  ({s/100:.2f})" if v != INVALID_TEMP and abs(s) < 15000 and s not in (0, 1) else ""
            print(f"{a:6d} = {v:6d}  0x{v:04X}{extra}")


def watch(m: ModbusRTU, period: float, csv_path: str | None):
    prev = None
    writer = None
    fh = None
    try:
        while True:
            t0 = time.time()
            raw = read_all(m)
            flat = {f"{t[0].upper()}{a}": v for t, vals in raw.items() for a, v in vals.items()}
            ts = time.strftime("%H:%M:%S")
            if csv_path:
                if writer is None:
                    new = not os.path.exists(csv_path)
                    fh = open(csv_path, "a", newline="")
                    writer = csv.writer(fh)
                    if new:
                        writer.writerow(["time"] + list(flat))
                writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S")] + list(flat.values()))
                fh.flush()
            if prev is None:
                print(f"{ts} baseline: {len(flat)} registers read in {time.time() - t0:.1f}s")
            else:
                changes = [f"{k}:{prev.get(k)}->{v}" for k, v in flat.items() if prev.get(k) != v
                           and k not in ("H28", "H29")]  # skip clock
                if changes:
                    print(f"{ts} " + "  ".join(changes))
            prev = flat
            time.sleep(max(0.0, period - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if fh:
            fh.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyUSB1")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--slave", type=int, default=1)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true")
    g.add_argument("--raw", action="store_true")
    g.add_argument("--watch", type=float, metavar="SEC")
    ap.add_argument("--csv", help="CSV log file for --watch")
    args = ap.parse_args()

    with ModbusRTU(args.port, args.baud, args.slave, timeout=0.5) as m:
        if args.watch:
            watch(m, args.watch, args.csv)
            return
        raw = read_all(m)
    if args.json:
        print(json.dumps(decoded(raw), indent=1, ensure_ascii=False))
    elif args.raw:
        print_raw(raw)
    else:
        print_decoded(raw)


if __name__ == "__main__":
    main()
