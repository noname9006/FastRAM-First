# FastRAM First

Makes Windows use dual-channel memory first on asymmetric RAM setups (for example 3 × 16 GB). An ACPI SRAT table describes the fast and slow zones as two NUMA nodes, and [OpenCore](https://github.com/acidanthera/OpenCorePkg) injects it at boot. Windows files and the firmware are not changed.

## The problem

In some cases a system has an asymmetric memory setup, such as 3 × 16 GB. The memory controller then divides the address space into two zones:

- **Dual-channel:** the capacity present in both channels. Data is interleaved between the channels.
- **Single-channel:** the remainder in the channel that has more memory. Theoretical bandwidth here is half as high.

Windows knows nothing about these zones and hands out pages from both of them mixed together. A program can get slow memory even while plenty of fast memory is free.

## What NUMA is

NUMA (Non-Uniform Memory Access) describes a computer in which each processor reaches some memory faster than other memory. Processors and memory are grouped into nodes. An ACPI table called SRAT describes which processors and memory belong together. According to [Microsoft](https://learn.microsoft.com/en-us/windows/win32/procthread/numa-support), Windows tries to satisfy a memory request from within the node, and allocates from other nodes if necessary.

That behavior is what this project relies on: if the fast memory and all the cores form one node, and the slow memory forms another, fast memory goes out first. The charts below show this on the test machine.

## Why this takes a workaround

Linux has a documented kernel boot parameter for emulating NUMA nodes: [`numa=fake`](https://docs.kernel.org/admin-guide/kernel-parameters.html), which [requires `CONFIG_NUMA_EMU`](https://docs.kernel.org/next/mm/numa_emulation.html). This project did not test it.

Windows has no equivalent for this purpose, as far as the documentation shows. Its closest option is [`bcdedit /set groupsize`](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/boot-parameters-to-test-drivers-for-multiple-processor-group-support), which is meant for testing and not for shipping systems. It creates a node for each processor group, based on processor counts, and the documentation gives no way to choose which physical memory goes into a node.

The firmware of the test machine has no SRAT table. So the node layout comes from a custom SRAT table, injected by a boot loader before Windows starts. On the test machine, Windows then reports two nodes.

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
