# Asymmetric memory on Windows: fast memory first

How to make Windows give programs fast (dual-channel) memory first and leave slow (single-channel) memory for last. No sticks need replacing: you add an ACPI SRAT table to the system that describes the fast and slow zones as two NUMA nodes.

> **Status.** Tested on one machine: Ryzen 5 5600X, 3 × 16 GB, 3733 MT/s, Windows 10. The steps are the same on other platforms, but the result is not guaranteed. A wrong change can stop the system from booting, so read "If something goes wrong" first.

## The problem

In some cases a system has an asymmetric memory setup, such as 3 × 16 GB. The memory controller then divides the address space into two zones:

- **Dual-channel:** the capacity present in both channels. Data is interleaved between the channels.
- **Single-channel:** the remainder in the channel that has more memory. Theoretical bandwidth here is half as high.

For example, 3 × 16 GB gives 32 GiB of fast memory and 16 GiB of slow memory.

The second part of the problem is that Windows knows nothing about these zones. To Windows all memory is the same, and a program gets pages from both zones mixed together. Speed can drop at any moment, depending not on how much memory is in use but on which pages the program received.

This is what a measurement of ordinary memory showed on the test machine. The system handed it out in this order:

```
fast 0.75 | SLOW 10.25 | fast 1 | slow 2 | FAST 29.75 | slow 1.75 | fast 0.25 GiB
```

So a program that needed 10 GiB got almost nothing but slow memory, even though 30 GiB of fast memory was free.

## The solution

Make fast memory go out first and slow memory last.

The physical addresses of the zones cannot be changed, because the BIOS sets them. The order of allocation can be changed, though. Windows [tries to allocate memory from within the NUMA node, and uses other nodes if necessary](https://learn.microsoft.com/en-us/windows/win32/procthread/numa-support). So you declare:

- **Node 0:** all cores and the fast memory.
- **Node 1:** only the slow memory, with no cores.

**The obstacle:** Windows treats a non-NUMA computer as one node. The firmware of the test machine has no SRAT table to describe nodes (check yours with `scripts/srat_dump.py`). So you create the table yourself and inject it at boot with the [OpenCore](https://github.com/acidanthera/OpenCorePkg) boot loader, which can add ACPI tables before Windows starts. Windows files and the firmware are not changed.

SRAT forbids nothing: all cores still see all memory. It is only a hint for allocation.

## Result on the test machine

Safe Mode, 25 runs, ordinary memory in 256 MiB chunks, from the first chunk handed out to the last:

| | Without SRAT | With SRAT |
|---|---|---|
| Allocation order | see above: mixed | **fast 30.5 GiB, then slow 15.25 GiB** |
| Fast zone, read / write / copy, GB/s | 42.2 / 29.8 / 39.4 | 42.5 / 29.8 / 39.4 |
| Slow zone, read / write / copy, GB/s | 27.5 / 26.7 / 22.0 | 27.2 / 26.6 / 21.9 |

The speed of the zones themselves does not change. What changes is which memory a program gets first. If more than the fast capacity is in use, the remainder still lands in the slow zone.

## What you need

- Windows 10 or 11, 64-bit, booting in UEFI mode.
- Python 3 and `pip install numpy matplotlib`.
- Files from this repository: the `scripts` folder.
- An [OpenCore release](https://github.com/acidanthera/OpenCorePkg/releases) and a plist editor ([ProperTree](https://github.com/corpnewt/ProperTree)).
- A FAT32 USB drive for the first trial.
- Your BitLocker recovery key if the disk is encrypted: changing the boot loader may ask for it. Save the key in advance.

## Step 1. Prepare

1. Finalize your memory setup: XMP/DOCP, frequency and BIOS options. Changing any of them can shift the zones, and the table will have to be created again.
2. Test the memory for stability with a long run, preferably several hours. Unstable memory can distort the measurements and corrupt data. We recommend [TestMem5](https://testmem.tz.ru/) with the [`extreme@anta777` preset](https://github.com/integralfx/MemTestHelper/blob/oc-guide/TM5-Configs/extreme%40anta777.cfg). Fix any errors before you continue.
3. Check that the system sees all the memory. Run `bcdedit` in an administrator console. If there is a `truncatememory` line, remove it with `bcdedit /deletevalue truncatememory` and reboot.
4. Give your account the "Lock pages in memory" right: `secpol.msc` > Local Policies > User Rights Assignment > "Lock pages in memory". Log off and on again. Windows Home has no `secpol.msc`, so you will need another way to grant the right.
5. Disable Secure Boot in the BIOS: OpenCore is not signed.

## Step 2. Find the zone boundary

**Take all measurements in Safe Mode.** Few programs and drivers run there, so less memory is occupied: the test covers almost the whole capacity, and other activity distorts the speed less. The script also works in normal mode, but part of the memory stays untested and the boundary may not be found: that is what happened in a short trial run in normal mode.

Boot into Safe Mode: Settings > Recovery > Advanced startup > Troubleshoot > Advanced options > Startup Settings > press `4`. Run:

```
python scripts/membench_phys.py
```

With the defaults this takes about 12 minutes on the test machine (25 runs). All flags are listed in [Script flags](#script-flags).

This produces, in the `scripts` folder, `membench_phys_<time>.csv` (the physical map) and `..._system.csv` (the allocation order). Details are in [membench_phys.md](membench_phys.md). Keep these files: they are your "before" state.

## Step 3. Create the table

In the same Safe Mode session, right after the measurement:

```
python scripts/make_srat.py --csv scripts/membench_phys_<time>.csv
```

`--csv` is required here because it names your measurement. The table is written to `SRAT.aml` in the current folder. The script finds the boundary from the read speed and reads the list of cores and the memory ranges from the system. It should report something like: `boundary 17 GiB, slow zone below it; 12 logical CPUs; 640 bytes`.

Sanity-check the result: the size of the slow zone should roughly equal the difference between the channel capacities.

The script stops with an error in two cases:

- **The speed is flat.** There is no difference between zones: the memory probably runs symmetrically, and you do not need the table.
- **There is more than one boundary.** Look at the BIOS settings first (see the section below). This script does not create a table with several boundaries. If you are sure there is a single boundary, set it by hand: `--boundary-gib <GiB> --slow below` (or `above`).

## Step 4. Set up OpenCore on the USB drive

1. Unpack the OpenCore release and find the `X64/EFI` folder. Copy it to the root of the USB drive, so that you have `EFI/BOOT/BOOTx64.efi` and `EFI/OC/OpenCore.efi`.
2. Copy `Docs/Sample.plist` to `EFI/OC/config.plist`.
3. Put `SRAT.aml` in `EFI/OC/ACPI/`.
4. In `EFI/OC/Drivers`, keep only `OpenRuntime.efi`.
5. Open `config.plist` in ProperTree and set:

| Parameter | Value |
|---|---|
| `ACPI > Add` | one entry: `Path` = `SRAT.aml`, `Enabled` = `True` |
| `ACPI > Delete`, `ACPI > Patch` | all entries `Enabled` = `False` |
| `Misc > Security > SecureBootModel` | `Disabled` |
| `Misc > Security > Vault` | `Optional` |
| `Misc > Security > ScanPolicy` | `0` |
| `Misc > Boot > ShowPicker` | `True` |
| `Misc > Boot > Timeout` | `5` |
| `PlatformInfo > UpdateSMBIOS` | `False` (Windows must not see altered computer data) |
| `Kernel > Add`, `UEFI > Drivers` | only what item 4 lists; `Kernel > Add` is empty |

`Sample.plist` changes from version to version, and parameter names may differ. Check against `Docs/Configuration.pdf` in your release.

## Step 5. Trial

1. Select the USB drive in the BIOS boot menu.
2. Select Windows in the OpenCore menu.
3. After startup, check the nodes in PowerShell:

```powershell
Add-Type -Name N -Namespace W -MemberDefinition '[DllImport("kernel32.dll")] public static extern bool GetNumaHighestNodeNumber(out uint n); [DllImport("kernel32.dll")] public static extern bool GetNumaAvailableMemoryNodeEx(ushort node, out ulong bytes);'
$n=0; [void][W.N]::GetNumaHighestNodeNumber([ref]$n); "highest node: $n"
0..$n | % { $b=0; [void][W.N]::GetNumaAvailableMemoryNodeEx($_,[ref]$b); "node $_ : {0:N2} GiB free" -f ($b/1GB) }
```

You should see `highest node: 1`, and the free memory of the nodes should roughly match the zones. If there is only one node, the table was not applied: either Windows started without going through OpenCore, or `config.plist` has an error.

Optional quick check of the allocation order, in normal mode. Close heavy programs first: by default the script takes all available memory except a 256 MiB safety margin, so the system may slow down while it runs.

```
python scripts/numa_check.py
```

The script takes memory in 2 GiB steps and prints the free memory of each node after every step. Node 0 should drain first, and node 1 only after that.

## Step 6. Verify the result

Again in Safe Mode, booted through OpenCore (Safe Mode is enabled the same way; the selection menu opens after OpenCore):

```
python scripts/membench_phys.py
python scripts/membench_phys_order_plot.py scripts/<before>_system.csv scripts/<after>_system.csv
```

The chart is written to `membench-phys-order.png` in the current folder. The grey (slow) area of the second panel (with SRAT) should be one block at the end. The threshold is found automatically from the data; you can set it with `--slow-read` if needed.

## Step 7. Make it permanent

Only when everything works from the USB drive:

1. Mount the EFI system partition in an administrator console: `mountvol S: /S`.
2. Copy `EFI/OC` from the USB drive to `S:\EFI\OC`. Do not touch the `S:\EFI\Microsoft` folder.
3. Add an OpenCore boot entry and put it first. You can do this in the BIOS if it lets you choose a file (`\EFI\OC\OpenCore.efi`), or with `bcdedit /enum firmware` and tools such as EasyUEFI.
4. Unmount the partition: `mountvol S: /D`.

Windows updates and BIOS resets can put Windows Boot Manager back in first place. The table then silently disappears, and the system works as it did before. If the speed starts to vary again, check with the command from step 5 first.

## Script flags

All flags are optional unless marked as required.

**`membench_phys.py`** (full details in [membench_phys.md](membench_phys.md))

| Flag | Default | What it affects |
|---|---|---|
| `--runs N` | 25 | Repeats of each measurement. More runs give steadier results and take longer. |
| `--passes N` | 3 | Passes per bin or chunk in each run; the best one is kept. |
| `--reserve N` | 256 | Safety margin: memory in MiB left to the system. A larger value is safer, but less memory gets tested. |
| `--max-gib X` | none | Takes at most X GiB, for a trial run. Too little for finding the boundary. |
| `--threads N` | CPU count | Worker threads for the measurement. |
| `--bin-mib N` | 256 | Size of one physical-address bin. Smaller bins locate the boundary more precisely. |
| `--min-tested-mib N` | 128 | Skips a bin or chunk with less memory than this, because small slices fit in the CPU cache and read too fast. |
| `--order-chunk-mib N` | 256 | Chunk size of the allocation-order tests. |
| `--no-system-order` | off | Skips the allocation-order test and its `_system.csv`. |
| `--awe-order` | off | Also measures the AWE allocation order and writes `_order.csv`. |
| `--node-order low-first / high-first` | `low-first` | Which NUMA node AWE asks for pages first. |
| `--boundary-gib X` | detected | Boundary used for the `_order.csv` statistics. |
| `--note "text"` | empty | Free text for the CSV header, such as timings or BIOS options. |
| `--out path.csv` | `membench_phys_<time>.csv` next to the script | Path of the main CSV. |

**`make_srat.py`**

| Flag | Default | What it affects |
|---|---|---|
| `--csv path` | required, unless both flags below are given | Main CSV of `membench_phys.py`; the boundary is found from it. |
| `--boundary-gib X` | none | Sets the boundary by hand. Use it only with `--slow` and only if the boundary is real. |
| `--slow below / above` | none | Which side of the boundary is the slow zone. |
| `--out path` | `SRAT.aml` | Output file. |

**`membench_phys_order_plot.py`**

| Flag | Default | What it affects |
|---|---|---|
| `csv ...` | required | One or more `_system.csv` or `_order.csv` files; one panel each. |
| `--labels L1 L2 ...` | file names | Panel titles. |
| `--out file.png` | `membench-phys-order.png` | Output image. |
| `--title "text"` | built-in title | Figure title. |
| `--slow-read X` | found from the data | Shades a chunk when its median read speed in GB/s is below X. |
| `--slow-pct X` | 50 | `_order.csv` only: shades a chunk when more than X % of its pages lie below the boundary. |

**`numa_check.py`**

| Flag | Default | What it affects |
|---|---|---|
| `--gib X` | all available memory | Takes at most X GiB. |
| `--step-gib X` | 2 | Size of one allocation step. |
| `--reserve N` | 256 | Safety margin: memory in MiB left to the system. |

`srat_dump.py` has no flags.

## BIOS settings that affect the result

On the test machine, the **DRAM Map Inversion** option was tested with the same sticks. `Auto` gave the best results, and `Disabled` gave noticeably lower read speed. Moving sticks between channels did not noticeably affect speed; the zones only shifted. On other boards these options have different names or may not exist. Changing any of them means repeating steps 2 and 3.

## If something goes wrong

| Symptom | What to do |
|---|---|
| Does not boot with OpenCore | Remove the USB drive or select Windows Boot Manager in the BIOS boot menu. Windows starts without the table. |
| Blue screen or hang when booting with the table | The same. Then disable the entry in `ACPI > Add` or create the table again. The usual cause is sticks or settings changed after the table was created. |
| BitLocker key prompt | Enter the saved key. |
| You changed sticks or memory settings | Boot without OpenCore first, then repeat steps 2 and 3. |

To undo everything, boot through Windows Boot Manager and delete `S:\EFI\OC` and its boot entry.

## Limitations

- The slow zone does not get faster. This method does not replace a symmetric configuration: two identical sticks are still faster, 46.9 versus 42 GB/s read on the author's machine.
- The system itself occupies part of the fast zone: on the author's machine, 30.5 of 32 GiB were available to programs in Safe Mode, and less in normal mode.
- Programs that manage NUMA themselves may behave differently. A process cannot be bound to node 1 because it has no cores (`start /node 1` will not work).
- The allocation order was tested for one large program on a clean system. How the file cache and several programs behave over long use was not measured.
- The script does not yet support processors with x2APIC: it stops with an error. Systems whose firmware already has its own SRAT (Threadripper, EPYC, multi-processor) are not suitable. Multi-die Ryzen processors with one memory controller should work but were not tested. Linux and other operating systems were not tested.

### Standby cache

Windows keeps recently used file data in RAM as the standby list, so that it does not have to read that data from the disk again. These pages [count as available memory](https://techcommunity.microsoft.com/blog/askperf/finally-a-windows-task-manager-performance-tab-blog/375332), and the memory manager reuses them when something else needs RAM.

The cache may therefore occupy part of the fast zone before you start a memory-hungry program, which would push that program toward the slow zone sooner. This is an expectation based on the allocation order, and it was not measured. How Windows chooses between standby pages in node 0 and free pages in node 1 was not measured either. For how the memory manager works in general, see chapter 5 of [Windows Internals, 7th edition, Part 1](https://learn.microsoft.com/en-us/sysinternals/resources/windows-internals).

Do not try to keep the standby cache permanently empty: data that has left it must be read from the SSD or HDD again, which increases disk load.

If you want to test it, you can empty the list once, right before starting such a program. Open [RAMMap](https://learn.microsoft.com/en-us/sysinternals/downloads/rammap) from Microsoft Sysinternals and select Empty > Empty Standby List. The effect is temporary, because Windows fills the cache again as files are read. This step was not tested with the SRAT table.

Windows has no built-in PowerShell command for this that we could find. Third-party tools and scripts rely on an undocumented system call, so this guide does not recommend them.

## Going through this with an AI agent

If you have an agent that can run commands on your computer (Claude Code, for example), give it this repository and write:

> Read docs/GUIDE.md and walk me through the steps. First collect system data, read-only: processor, sticks, boot mode, Secure Boot, BitLocker, `truncatememory`. Tell me whether the machine is suitable. Do not run commands that change the boot process, BIOS or EFI partition yourself: show them to me and explain them. I will run the test in Safe Mode myself and give you the CSV. Show me the output of `make_srat.py` and explain why the boundary is plausible before going further.

Reboots, BIOS settings and boot changes are best done yourself: an agent cannot help if the system does not start, so keep this guide open on your phone beforehand.
