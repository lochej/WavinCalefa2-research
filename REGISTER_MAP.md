# Wavin Calefa II (DHW 212 V ITC) – Modbus register map

Discovered on 2026-11-07 by full address-space scan (`scan.py`) and live
observation (`wavin_calefa.py --watch`). Device: RJ-M port, RTU 9600 8N1,
slave 1, FW 2.12, HW 8, dev type 3.

**Addresses are raw 0-based PDU addresses** (what goes on the wire). The Sentio
document's numbers map 1:1 onto them (no −1 offset).

## General rules

* Temperatures: signed int16 × 0.01 °C. `32767` (0x7FFF) = not available / no sensor.
* Any multi-register read that touches an invalid address fails with exception 2,
  so only read inside the valid ranges below.
* FC01 (coils) is not supported. FC03 / FC04 / FC02 work.
* A full poll of all ~1200 values takes ~4.5 s at 9600 bps.
* Writes with FC06 (write single register) work: tested on HR 6521, 7501 and 7705 from ESPHome; the display follows immediately.

## Valid ranges

| Table | Ranges |
|---|---|
| Holding (FC03) | 3-43, 50, 6501-6519, 6521-6538, 7301-7306, 7501-7525, 7701-7724, 10001-10041, 10046, 10050-10061, 10063-10190 |
| Input (FC04) | 1-2, 10-27, 6502-6515, 7301-7310, 7501-7511, 7701-7724, 10001-10011, 10017-10728, 12801-12807, 12901-12904 … 12961-12964 (step 10) |
| Discrete (FC02) | 1-5, 6503-6517, 7301-7302, 7304-7310, 7501-7512, 7701-7706 |

## Confirmed / high-confidence values

✔ = confirmed by observation, ~ = strong guess, ? = guess

### Sensors (thermistor inputs T1–T7)

| Sensor | Raw IR | Role-mapped IR | Meaning | |
|---|---|---|---|---|
| T1 | 12801 | 7702, 10001, 10017 | Heating return | ✔ |
| T2 | 12802 | 7701, 10002, 10018 | Heating flow (supply) | ✔ |
| T3 | 12803 | 6509, 10003 | Cold water inlet (DCW) | ✔ (dropped to 11.8 °C when tapping) |
| T4 | 12804 | 6505, 10004 | DHW outlet (hot tap water) | ✔ (regulated to the 50 °C setpoint) |
| T5 | 12805 | 6506, 10005 | Primary (district heating) supply | ✔ |
| T6 | 12806 | 6507, 10006 | Primary return | ✔ (dropped to 17 °C when tapping) |
| T7 | 12807 | — | not connected (32767) | ✔ |

`129x1..129x4` (x = sensor 0..6): temperature, ADC count (12-bit, NTC: lower = hotter, 4090 = open), status word, signed offset.

### Location / system

| Reg | R/W | Meaning | |
|---|---|---|---|
| HR 3 | RW | Modbus slave address | ✔ |
| HR 4-5 | RW | Baudrate (uint32) | ✔ |
| HR 6 | RW | Modbus mode (2 = READ_WRITE) | ✔ |
| HR 7 / 8 | RW | Parity (0 = none) / stop bits (0 = 1) | ✔ |
| HR 10-25 | RW | Location name (string, 2 chars per register, big-endian) | ✔ |
| HR 26 / 27 | RW | Standby / Vacation | ~ |
| HR 28-29 | R | Clock, uint32 epoch **in local time** (not UTC) | ✔ |
| HR 32 | R | Timezone offset, s (3600 = UTC+1; unit is in Denmark) | ✔ |
| HR 33 | R | DST flag/offset? (0 in winter) | ? |
| IR 10-16 | R | dev type, HW, SW major/minor, serial prefix, serial (uint32) | ✔ |
| IR 20 / 21 / 22 | R | Outdoor temperature: actual / filtered / averaged (matched ~5 °C outside) | ✔ |
| IR 27 | R | Uptime, s (updated every 60 s) | ✔ |
| IR 10727 | R | Uptime counter, s | ✔ |
| IR 10666-10667 | R | Boot time (uint32, local epoch) | ✔ |
| IR 10010 | R | Temperature ~21 °C (room or board?) | ? |
| IR 19 (=10008) | R | Temperature ~32 °C (board / internal?) | ? |
| DI 1 / 2 | R | Aggregated warning / error | ~ |

### Domestic hot water (65xx)

| Reg | R/W | Meaning | |
|---|---|---|---|
| HR 6501-6516 | RW | DHW name ("Varmt brugsvand") | ✔ |
| HR 6517 | RW | DHW mode: 0 SCHEDULE, 1 SCHEDULE_ADAPTIVE, 2 ECO, 3 COMFORT | ~ |
| HR 6518 | RW | Display access level (<40 user, ≥40 installer) | ~ |
| HR 6519 | RW | Block request | ~ |
| HR 6521 | RW | **DHW setpoint** (5000 = 50 °C); Modbus write tested OK | ✔ |
| HR 6522 | RW | Bypass temperature (40 °C) | ~ |
| HR 6523 | RW | Circulation pump present | ~ |
| HR 6524 | RW | Circulation inlet temperature (45 °C) | ~ |
| HR 6529 | R(W?) | DHW valve command (moves only while tapping) | ? |
| HR 6525-6538 | RW | other DHW parameters (undocumented) | ? |
| IR 6502 | R | **DHW state: 2 = idle, 1 = tapping** (differs from the Sentio doc) | ✔ |
| IR 6505 | R | DHW outlet temperature (T4) | ✔ |
| IR 6506 | R | Primary supply temperature (T5) | ✔ |
| IR 6507 | R | Primary return temperature (T6) | ✔ |
| IR 6509 | R | Cold water temperature (T3) | ✔ |
| IR 6510 | R | **DHW flow, l/h** (≈ 405 while tapping, 0 otherwise; checked with 2 L filled in ~17 s ≈ 424 l/h) | ✔ |
| IR 10671 | R | DHW flow, unfiltered (noisier copy of IR 6510) | ~ |
| IR 6511 | R | DHW valve position (follows HR 6529) | ~ |
| IR 6513 | R | DHW regulator phase (4 idle, 2→3 tapping) | ~ |
| IR 6514 | R | 830, constant | ? |
| HR 10032-10035 | R | DHW PID internals (signed), active only while tapping | ? |
| HR 10041 | R | DHW regulator phase (8 idle, 3/5 tapping) | ? |
| DI 6503-6509 | R | DHW alarms (low energy, temp high, motor, DHI/DHO/DHW/DCW sensor) per the Sentio doc | ? |

### Room presets (75xx)

| Reg | R/W | Meaning | |
|---|---|---|---|
| HR 7501 | RW | Currently selected room setpoint; Modbus write tested OK | ✔ |
| HR 7502 | RW | Preset ECO (18 °C) | ✔ |
| HR 7503 | RW | Preset COMFORT (20 °C) | ✔ |
| HR 7504 | RW | Preset EXTRA COMFORT (23 °C) | ✔ |
| IR 7510 / 7511 | R | Active room setpoint (follows HR 7501) | ✔ |

### Heating circuit / ITC (73xx, 77xx)

| Reg | R/W | Meaning | |
|---|---|---|---|
| IR 7310 (= IR 10009) | R | **Heating circuit pressure**, ×0.01 bar (matches the display: 1.6 bar = 160) | ✔ |
| IR 7701 | R | Heating supply temperature (T2) | ✔ |
| IR 7702 | R | Heating return temperature (T1) | ✔ |
| IR 7703 | R | Heating flow target (heat curve output) | ~ |
| IR 7706 (= IR 7304 = HR 7302) | R | ITC valve opening / heat demand (×0.01 %?) | ~ |
| IR 7301 | R | Heating active (1/0) | ~ |
| IR 7704 / 7705 | R | Pump demand / state? | ? |
| HR 7701 | RW | **Heat curve slope** ×0.1 (13 = 1.3); confirmed by changing 1.2 → 1.3 on the display; Modbus write (1.2 → 1.4) tested OK, display follows | ✔ |
| HR 7703 | RW | Heat curve slope, second copy (changed together with HR 7701) | ~ |
| HR 7705 | RW | **Radiator heat offset** (800 = 8 °C); Modbus write tested OK, display follows | ✔ |
| HR 7706 | RW | **Heat curve minimum flow temperature** (3700 = 37 °C) | ✔ |
| HR 7707 | RW | **Heat curve maximum flow temperature** (4900 = 49 °C) | ✔ |
| HR 7708 | RW | ITC regulator P gain ×0.1 (15 = 1.5) | ~ |
| HR 7709 | RW | **ITC regulator I time** (20 → 21 confirmed) | ✔ |
| HR 7713 | RW | Return limiter mode (2 = maximum?) | ? |
| HR 7714 | RW | Return limiter minimum limit? (4000 = 40 °C) | ? |
| HR 7715 | RW | Return limiter gain at the minimum limit? ×0.1 (+2.0) | ? |
| HR 7716 | RW | **Return limiter maximum temperature** (4000 → 3900 confirmed) | ✔ |
| HR 7717 | RW | Return limiter gain at the maximum limit, signed ×0.1 (−2.0) | ~ |
| HR 7718 | RW | **Return limiter priority over flow temperature** 0 OFF / 1 ON (confirmed) | ✔ |
| HR 7702, 7704, 7710-7712, 7719-7724 | RW | Other ITC parameters (7704 = 10, 7710 = 500, 7712 = 2500 …) | ? |

Hysteresis (1.0 → 1.1) and offset (5 → 6) changed **no** Modbus register (holding, input or discrete), so they are either not exposed or stored only in the display.

## Corrections to `Wavin_Calefa_II_Modbus_Report.pdf`

* HR 4 is not unused: HR 4-5 together form the uint32 baudrate.
* "6505 = DHW temperature" is true only for **input** register 6505. Holding 6505 is part of the name string.
* 7305 is not the heating flow temperature: IR 7305 = 32767, HR 7305 = 255. The flow temperature is IR 7701.
* HR 28-29 is a local-time epoch, not a true Unix timestamp.

## Still open

* Units and scale of IR 6511 / HR 6529 (valve).
* Holding block 7700 (heat curve parameters), 10001-10190, the 6525-6538 extra parameters, and input block 10017-10728 (mostly zero, possibly statistics or energy counters).
* The DI 7501-7512 bits (all 1).
