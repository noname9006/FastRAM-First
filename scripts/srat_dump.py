"""
srat_dump.py - read-only: shows which ACPI tables the firmware exposes and decodes SRAT/SLIT.
Windows, Python 3, no admin rights needed. Writes nothing except the raw tables it finds, to the current folder.

Usage:  python srat_dump.py
"""
import ctypes
import struct
import sys

PROV_ACPI = int.from_bytes(b"ACPI", "big")  # 'ACPI' provider signature

k32 = ctypes.windll.kernel32
k32.EnumSystemFirmwareTables.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
k32.GetSystemFirmwareTable.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]


def list_tables():
    size = k32.EnumSystemFirmwareTables(PROV_ACPI, None, 0)
    if not size:
        return []
    buf = ctypes.create_string_buffer(size)
    k32.EnumSystemFirmwareTables(PROV_ACPI, buf, size)
    raw = buf.raw[:size]
    return [raw[i:i + 4].decode("ascii", "replace") for i in range(0, len(raw), 4)]


def get_table(sig):
    tid = int.from_bytes(sig.encode("ascii"), "little")
    size = k32.GetSystemFirmwareTable(PROV_ACPI, tid, None, 0)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    k32.GetSystemFirmwareTable(PROV_ACPI, tid, buf, size)
    return buf.raw[:size]


def gib(n):
    return f"{n / 2**30:.3f} GiB"


def decode_srat(data):
    sig, length, rev, csum = struct.unpack_from("<4sIBB", data, 0)
    oem_id = data[10:16].decode("ascii", "replace")
    oem_tbl = data[16:24].decode("ascii", "replace")
    print(f"SRAT: length={length} revision={rev} OEM={oem_id!r}/{oem_tbl!r}")
    off = 48  # 36 header + 4 table revision + 8 reserved
    cpus = {}
    mems = []
    while off + 2 <= len(data):
        etype, elen = data[off], data[off + 1]
        if elen == 0:
            print("  !! zero-length entry, stopping")
            break
        e = data[off:off + elen]
        if etype == 0 and elen >= 16:  # Processor Local APIC/SAPIC
            dom = e[2] | (e[9] << 8) | (e[10] << 16) | (e[11] << 24)
            apic = e[3]
            flags = struct.unpack_from("<I", e, 4)[0]
            cpus.setdefault(dom, []).append((apic, flags & 1))
        elif etype == 1 and elen >= 40:  # Memory affinity
            dom = struct.unpack_from("<I", e, 2)[0]
            base = struct.unpack_from("<Q", e, 8)[0]
            ln = struct.unpack_from("<Q", e, 16)[0]
            flags = struct.unpack_from("<I", e, 28)[0]
            mems.append((dom, base, ln, flags))
        elif etype == 2 and elen >= 24:  # Processor x2APIC
            dom = struct.unpack_from("<I", e, 4)[0]
            apic = struct.unpack_from("<I", e, 8)[0]
            flags = struct.unpack_from("<I", e, 12)[0]
            cpus.setdefault(dom, []).append((apic, flags & 1))
        else:
            print(f"  (entry type {etype}, len {elen} - not decoded)")
        off += elen

    print("\nProcessor affinity (proximity domain -> APIC ids, enabled flag):")
    for dom, lst in sorted(cpus.items()):
        print(f"  domain {dom}: {len(lst)} entries, enabled={sum(f for _, f in lst)}")
    print("\nMemory affinity:")
    for dom, base, ln, flags in mems:
        print(f"  domain {dom}: {base:#014x} - {base + ln:#014x}  ({gib(ln)})  "
              f"enabled={flags & 1} hotplug={(flags >> 1) & 1} nonvolatile={(flags >> 2) & 1}")
    print(f"\nTotal in SRAT memory entries: {gib(sum(m[2] for m in mems if m[3] & 1))}")


def decode_slit(data):
    n = struct.unpack_from("<Q", data, 36)[0]
    print(f"SLIT: {n} localities")
    for i in range(n):
        row = data[44 + i * n: 44 + (i + 1) * n]
        print("  ", list(row))


def main():
    if sys.platform != "win32":
        sys.exit("Windows only")
    tables = list_tables()
    print("ACPI tables:", " ".join(tables) or "(none)")
    print(f"Windows highest NUMA node: {_numa_highest()}")
    print()
    for sig in ("SRAT", "SLIT", "HMAT", "MSCT"):
        if sig not in tables:
            print(f"{sig}: not present\n")
            continue
        data = get_table(sig)
        with open(f"{sig}.bin", "wb") as f:
            f.write(data)
        print(f"{sig}: {len(data)} bytes, saved to {sig}.bin")
        if sig == "SRAT":
            decode_srat(data)
        elif sig == "SLIT":
            decode_slit(data)
        print()


def _numa_highest():
    n = ctypes.c_ulong(0)
    k32.GetNumaHighestNodeNumber(ctypes.byref(n))
    return n.value


if __name__ == "__main__":
    main()
