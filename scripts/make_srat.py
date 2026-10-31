"""
make_srat.py - builds an ACPI SRAT table that splits memory into a fast and a slow NUMA node (Windows, read-only for the system).

All CPUs and the fast zone go to node 0, the slow zone to node 1. Windows then hands out node 0 memory first.
The result is a file; inject it with OpenCore (ACPI > Add). See docs/asymmetric-memory-guide.md.

Usage: python make_srat.py --csv membench_phys_XXXX.csv --out SRAT.aml      (finds the boundary in the physical map)
       python make_srat.py --boundary-gib 17 --slow below --out SRAT.aml    (set it by hand)
Needs: membench_phys.py next to this script, numpy. Rerun after any change of sticks or memory BIOS options.
"""
import argparse
import csv
import ctypes
import statistics
import struct
import sys

from membench_phys import GiB, find_boundary, physical_ranges


def get_madt():
    k32 = ctypes.windll.kernel32
    k32.GetSystemFirmwareTable.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    k32.GetSystemFirmwareTable.restype = ctypes.c_uint32
    prov, tid = int.from_bytes(b"ACPI", "big"), int.from_bytes(b"APIC", "little")
    n = k32.GetSystemFirmwareTable(prov, tid, None, 0)
    buf = ctypes.create_string_buffer(n)
    k32.GetSystemFirmwareTable(prov, tid, buf, n)
    return buf.raw[:n]


def enabled_apic_ids(madt):
    ids, off = [], 44
    while off + 2 <= len(madt):
        typ, length = madt[off], madt[off + 1]
        if typ == 9:
            sys.exit("MADT has x2APIC entries: this script only writes the 8-bit form, extend it first.")
        if typ == 0 and struct.unpack_from("<I", madt, off + 4)[0] & 1:
            ids.append(madt[off + 3])
        off += length
    return sorted(ids)


def boundary_from_csv(path):
    """(boundary GiB, 'below'|'above'): found from the read speed per bin."""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    bins = {}
    for r in rows:
        if r["read_gbs"]:
            bins.setdefault(float(r["start_gib"]), []).append(float(r["read_gbs"]))
    pts = sorted((s, statistics.median(v)) for s, v in bins.items())
    boundary, side, why = find_boundary(pts)
    if boundary is None:
        sys.exit(f"Cannot build the table: {why}. Look at the csv; set the boundary by hand only if it is real.")
    return boundary, side


def build(apic_ids, ranges, boundary, slow):
    b = int(boundary * GiB)
    body = b""
    for a in apic_ids:
        body += struct.pack("<BBBBIB3sI", 0, 16, 0, a, 1, 0, b"\0\0\0", 0)
    for start, length in ranges:
        for s, e in ((start, min(start + length, b)), (max(start, b), start + length)):
            if e <= s:
                continue
            is_low = s < b
            node = 1 if is_low == (slow == "below") else 0
            body += struct.pack("<BBIHQQIIQ", 1, 40, node, 0, s, e - s, 0, 1, 0)
    length = 48 + len(body)
    head = bytearray(b"SRAT" + struct.pack("<IBB", length, 3, 0) + b"MEMSPL" + b"SRATSPLT"
                     + struct.pack("<I", 1) + b"PY  " + struct.pack("<I", 1) + struct.pack("<I", 1) + bytes(8))
    table = bytearray(head) + body
    table[9] = (-sum(table)) & 0xFF
    return bytes(table)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="main csv of membench_phys.py")
    ap.add_argument("--boundary-gib", type=float)
    ap.add_argument("--slow", choices=("below", "above"), help="on which side of the boundary the slow zone is")
    ap.add_argument("--out", default="SRAT.aml")
    a = ap.parse_args()
    if a.csv:
        boundary, slow = boundary_from_csv(a.csv)
    elif a.boundary_gib is not None and a.slow:
        boundary, slow = a.boundary_gib, a.slow
    else:
        sys.exit("Give --csv, or --boundary-gib with --slow.")
    ids, ranges = enabled_apic_ids(get_madt()), physical_ranges()
    table = build(ids, ranges, boundary, slow)
    with open(a.out, "wb") as f:
        f.write(table)
    print(f"boundary {boundary:g} GiB, slow zone {slow} it; {len(ids)} logical CPUs; {len(table)} bytes -> {a.out}")


if __name__ == "__main__":
    main()
