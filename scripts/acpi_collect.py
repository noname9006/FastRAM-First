"""
acpi_collect.py - read-only. Saves every ACPI table to ./acpi_tables/, decodes MADT (CPU APIC IDs)
and prints the physical memory map Windows sees (registry, no admin needed).

Usage:  python acpi_collect.py > acpi_report.txt
"""
import ctypes
import os
import struct
import winreg

PROV_ACPI = int.from_bytes(b"ACPI", "big")
k32 = ctypes.windll.kernel32
k32.EnumSystemFirmwareTables.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
k32.GetSystemFirmwareTable.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]


def list_tables():
    size = k32.EnumSystemFirmwareTables(PROV_ACPI, None, 0)
    buf = ctypes.create_string_buffer(size)
    k32.EnumSystemFirmwareTables(PROV_ACPI, buf, size)
    raw = buf.raw[:size]
    return [raw[i:i + 4].decode("ascii", "replace") for i in range(0, len(raw), 4)]


def get_table(sig):
    tid = int.from_bytes(sig.encode("ascii"), "little")
    size = k32.GetSystemFirmwareTable(PROV_ACPI, tid, None, 0)
    buf = ctypes.create_string_buffer(size)
    k32.GetSystemFirmwareTable(PROV_ACPI, tid, buf, size)
    return buf.raw[:size]


def gib(n):
    return f"{n / 2**30:.3f} GiB"


def decode_madt(d):
    print(f"MADT: length={len(d)} revision={d[8]} local APIC addr={struct.unpack_from('<I', d, 36)[0]:#x}")
    off = 44
    while off + 2 <= len(d):
        t, ln = d[off], d[off + 1]
        if ln == 0:
            break
        e = d[off:off + ln]
        if t == 0 and ln >= 8:
            fl = struct.unpack_from("<I", e, 4)[0]
            print(f"  LAPIC  acpi_id={e[2]:3d} apic_id={e[3]:3d} enabled={fl & 1} online_capable={(fl >> 1) & 1}")
        elif t == 9 and ln >= 16:
            apic, fl, uid = struct.unpack_from("<III", e, 4)
            print(f"  x2APIC uid={uid:3d} apic_id={apic:3d} enabled={fl & 1}")
        off += ln


def physical_memory_map():
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                         r"HARDWARE\RESOURCEMAP\System Resources\Physical Memory")
    data, _ = winreg.QueryValueEx(key, ".Translated")
    count = struct.unpack_from("<I", data, 0)[0]
    off = 4
    ranges = []
    for _ in range(count):
        # CM_FULL_RESOURCE_DESCRIPTOR: InterfaceType, BusNumber, then PartialResourceList header (8 bytes)
        off += 8
        _ver, _rev, n = struct.unpack_from("<HHI", data, off)
        off += 8
        for _ in range(n):
            rtype, _share, flags = struct.unpack_from("<BBH", data, off)
            start, length = struct.unpack_from("<QI", data, off + 4)
            if rtype in (3, 7):  # CmResourceTypeMemory, CmResourceTypeMemoryLarge (ranges above 4 GiB)
                if flags & 0x200:
                    length <<= 8
                elif flags & 0x400:
                    length <<= 16
                elif flags & 0x800:
                    length <<= 32
                ranges.append((start, length))
            off += 20
    return ranges


def main():
    tables = list_tables()
    os.makedirs("acpi_tables", exist_ok=True)
    print("ACPI tables:", " ".join(tables))
    seen = {}
    for sig in tables:
        data = get_table(sig)
        seen[sig] = seen.get(sig, 0) + 1
        name = f"acpi_tables/{sig}_{seen[sig]}.bin"
        with open(name, "wb") as f:
            f.write(data)
        if sig == "MADT" or sig == "APIC":
            print()
            decode_madt(data)
    print("\nPhysical memory ranges seen by Windows:")
    total = 0
    for start, length in physical_memory_map():
        total += length
        print(f"  {start:#014x} - {start + length:#014x}  ({gib(length)})")
    print(f"Total: {gib(total)}")


if __name__ == "__main__":
    main()
