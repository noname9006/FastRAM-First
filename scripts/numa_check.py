"""
numa_check.py - shows how Windows sees the two memory nodes and which node it takes pages from first.

1. Prints the highest NUMA node and available memory per node.
2. Allocates and touches memory in 2 GiB steps (ordinary process memory, no special rights) and prints
   available memory per node after each step. If the fast node (0) drains first and the slow node (1)
   only afterwards, the SRAT trick works.

Needs: pip install numpy
Usage: python numa_check.py            (takes all available memory except the safety margin)
       python numa_check.py --gib 40   (takes at most 40 GiB)
Close big programs first. Memory is released when the script exits.
"""
import argparse
import ctypes
import sys
import time

import numpy as np

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetNumaAvailableMemoryNodeEx.argtypes = [ctypes.c_ushort, ctypes.POINTER(ctypes.c_ulonglong)]
k32.GetNumaHighestNodeNumber.argtypes = [ctypes.POINTER(ctypes.c_ulong)]


def highest_node():
    n = ctypes.c_ulong(0)
    k32.GetNumaHighestNodeNumber(ctypes.byref(n))
    return n.value


def avail(node):
    b = ctypes.c_ulonglong(0)
    if not k32.GetNumaAvailableMemoryNodeEx(node, ctypes.byref(b)):
        return None
    return b.value / 2**30


def snapshot(nodes):
    return [avail(n) for n in range(nodes + 1)]


def fmt(vals):
    return "  ".join("n/a" if v is None else f"{v:6.2f}" for v in vals)


def main():
    if sys.platform != "win32":
        sys.exit("Windows only")
    ap = argparse.ArgumentParser()
    ap.add_argument("--gib", type=float, default=None, help="take at most this much (default: all available memory)")
    ap.add_argument("--step-gib", type=float, default=2, help="size of one allocation step (default 2)")
    ap.add_argument("--reserve", type=int, default=256, help="safety margin: memory in MiB left available to the system (default 256)")
    args = ap.parse_args()

    hi = highest_node()
    print(f"Highest NUMA node: {hi}")
    if hi == 0:
        print("Windows sees ONE node: the SRAT was not applied. Run srat_dump.py to see what the firmware exposes.")
    start = snapshot(hi)
    print("Available GiB per node at start: " + fmt(start) + f"   (sum {sum(v for v in start if v):.2f})\n")

    header = "allocated  " + "  ".join(f"node{n:<2d}" for n in range(hi + 1))
    print(header)
    held = []
    step = int(args.step_gib * 2**30)
    total = 0
    while args.gib is None or total < args.gib * 2**30:
        if sum(v for v in snapshot(hi) if v) < args.reserve / 1024 + args.step_gib:
            print("Safety margin reached.")
            break
        buf = np.empty(step, dtype=np.uint8)
        buf[:] = 1  # touch every page
        held.append(buf)
        total += step
        time.sleep(0.3)
        print(f"{total / 2**30:6.1f} GiB  " + fmt(snapshot(hi)), flush=True)

    print("\nHolding memory; press Enter to release and exit.")
    input()


if __name__ == "__main__":
    main()
