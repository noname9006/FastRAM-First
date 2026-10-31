# FastRAM First

Makes Windows use dual-channel memory first on asymmetric RAM setups (for example 3 × 16 GB). An ACPI SRAT table describes the fast and slow zones as two NUMA nodes, and [OpenCore](https://github.com/acidanthera/OpenCorePkg) injects it at boot. Windows files and the firmware are not changed.

## The problem

In some cases a system has an asymmetric memory setup, such as 3 × 16 GB. The memory controller then divides the address space into two zones:

- **Dual-channel:** the capacity present in both channels. Data is interleaved between the channels.
- **Single-channel:** the remainder in the channel that has more memory. Theoretical bandwidth here is half as high.

Windows knows nothing about these zones and hands out pages from both of them mixed together. A program can get slow memory even while plenty of fast memory is free.

## What NUMA is

NUMA (Non-Uniform Memory Access) is a way to describe a computer whose memory is not equally fast for every processor core. Cores and memory are grouped into nodes. The firmware reports the nodes to the operating system in an ACPI table called SRAT. By default, the operating system then tries to give a program memory from the node closest to the core it runs on, and uses other nodes only when that memory runs out.

That allocation order is what this project relies on: if the fast memory and all the cores form one node, and the slow memory forms another, fast memory goes out first.

## Why this takes a workaround

Linux can emulate NUMA nodes with a kernel boot parameter (`numa=fake`, on kernels built with NUMA emulation support), so no firmware table is needed there.

Windows has no such option. It only sees the nodes that the firmware reports, and a typical desktop system reports none. So the node layout has to come from a custom SRAT table, injected before Windows starts by a boot loader.

## The result

The top chart shows the order in which Windows hands out memory without the table, and the bottom chart shows it with the table. Grey marks the slow zone. Fast memory now goes out first and slow memory last, while the speed of each zone stays the same.

![RAM speed from the first to the last chunk handed out, without and with SRAT](docs/srat-order-compare.png)

## How to use it

1. Measure the memory in Safe Mode with `membench_phys.py`.
2. Build the table with `make_srat.py`.
3. Inject `SRAT.aml` at boot with OpenCore and verify the result.

**Before you start, read the full guide: [asymmetric-memory-guide.md](asymmetric-memory-guide.md)**

## Disclaimer

Use this project at your own risk. You alone are responsible for any damage that results from using it, including but not limited to data loss, system instability, failure to boot and hardware damage. The software is provided "as is", without warranty of any kind (see [LICENSE](LICENSE)). Read the guide in full and back up your data before you start.

## Tested on

Everything was run and checked on this one machine only. Results on other hardware may differ.

| Component | Details |
|---|---|
| CPU | AMD Ryzen 5 5600X |
| Motherboard | ASRock B550 Steel Legend, BIOS P4.00 |
| RAM | 48 GB (3 × 16 GB) at 3733 MT/s: G.Skill F4-3600C16-16GVKC in channel A, Crucial Ballistix BL16G36C16U4B.M8FB1 in channels A and B |
| OS | Windows 10 Pro N, 64-bit (build 19045) |

## Files

| File | Purpose |
|---|---|
| `membench_phys.py` | Measures memory speed along physical addresses and allocation order ([docs](membench_phys.md)) |
| `membench_phys_order_plot.py` | Charts the allocation order results |
| `make_srat.py` | Builds `SRAT.aml` from the measurements |
| `membench.py` | Older virtual-memory benchmark for RAM and VRAM; `membench_phys.py` reuses its hardware readers |
| `acpi_collect.py`, `srat_dump.py` | Read-only ACPI diagnostics |
| `numa_check.py` | Shows which NUMA node Windows takes memory from first |

## Requirements

Windows 10 or 11 (64-bit, UEFI), Python 3, `pip install numpy matplotlib`, and a [release of OpenCore](https://github.com/acidanthera/OpenCorePkg/releases).
