#!/usr/bin/env python3
"""Discover every readable address of a Wavin Calefa II over Modbus RTU.

The Calefa rejects (exception 2) any multi-register read that touches a single
invalid address, so empty regions cannot be skipped with large block reads.
Wavin firmware groups data per object in blocks of 100 addresses (Sentio doc:
LOCATION 000xx, ROOM 001xx.., OUTDOOR 033xx, DHW 065xx, HCC 077xx...), with
values starting at offset 0..~10 of the block.  So:

  phase 1 (coarse):  probe offsets 0..PROBE-1 of every 100-block, single reads
  phase 2 (detail):  read every address of each block that answered

Result -> JSON (addresses are raw 0-based PDU addresses).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from modbus_rtu import ModbusError, ModbusException, ModbusRTU

TABLES = {"holding": 3, "input": 4, "discrete": 2, "coils": 1}


def read1(m: ModbusRTU, fc: int, addr: int):
    """Return value, None if illegal address. Raises on unsupported function."""
    for attempt in range(3):
        try:
            if fc in (1, 2):
                return int(m.read_bits(fc, addr, 1)[0])
            return m.read_registers(fc, addr, 1)[0]
        except ModbusException as e:
            if e.code == 1:
                raise
            return None
        except ModbusError:
            if attempt == 2:
                print(f"\n  ! no valid answer at {addr}", file=sys.stderr)
                return None
            time.sleep(0.2)


def ranges(addrs):
    out, s = [], None
    for i, a in enumerate(addrs):
        if s is None:
            s = a
        if i + 1 == len(addrs) or addrs[i + 1] != a + 1:
            out.append(f"{s}-{a}" if s != a else str(s))
            s = None
    return ", ".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyUSB1")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--slave", type=int, default=1)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=65535)
    ap.add_argument("--probe", type=int, default=10, help="offsets probed per 100-block in phase 1")
    ap.add_argument("--tables", default="holding,input,discrete,coils")
    ap.add_argument("--out", default="scan_result.json")
    args = ap.parse_args()

    result = {"port": args.port, "baud": args.baud, "slave": args.slave,
              "time": time.strftime("%Y-%m-%d %H:%M:%S"), "tables": {}}
    m = ModbusRTU(args.port, args.baud, args.slave, timeout=0.3)
    for name in args.tables.split(","):
        fc = TABLES[name]
        t0 = time.time()
        try:
            # phase 1
            hit_blocks = []
            first = args.start - args.start % 100
            for base in range(first, args.end + 1, 100):
                for off in range(args.probe):
                    a = base + off
                    if a < args.start or a > args.end:
                        continue
                    if read1(m, fc, a) is not None:
                        hit_blocks.append(base)
                        break
                print(f"\r{name} phase1: {base}/{args.end}  blocks={hit_blocks[-8:]}   ",
                      end="", file=sys.stderr)
            print(f"\n{name}: blocks with data: {hit_blocks}", file=sys.stderr)
            # phase 2
            found = {}
            for base in hit_blocks:
                for a in range(max(base, args.start), min(base + 100, args.end + 1)):
                    v = read1(m, fc, a)
                    if v is not None:
                        found[a] = v
                print(f"\r{name} phase2: block {base}  total={len(found)}   ", end="", file=sys.stderr)
        except ModbusException as e:
            print(f"\n{name}: {e}", file=sys.stderr)
            result["tables"][name] = {"error": str(e)}
            continue
        print(f"\n{name}: done in {time.time() - t0:.0f}s: {ranges(sorted(found))}", file=sys.stderr)
        result["tables"][name] = {"blocks": hit_blocks,
                                  "values": {str(k): v for k, v in sorted(found.items())}}
        with open(args.out, "w") as f:  # save after each table
            json.dump(result, f, indent=1)
    m.close()
    print(f"written {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
