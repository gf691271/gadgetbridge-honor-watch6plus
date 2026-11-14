# Gadgetbridge for HONOR Watch 6 Plus

Practical notes, patches and tooling for pulling complete health data off an
**HONOR Watch 6 Plus (Rome-B19C)** with [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge),
and exporting it as files that other programs can consume without depending on
Gadgetbridge itself.

This is a research notebook, not a fork. No Gadgetbridge source and no APK is
vendored here — only the patches, the device notes and the tooling needed to
rebuild the same environment.

---

## Device profile

| | |
|---|---|
| Watch | HONOR Watch 6 Plus, model name `Rome-B19C` |
| Firmware | `20.1.0.114` |
| Phone | HONOR Magic V6 `PNM-AN20`, Android 17 / SDK 37 (MagicOS) |
| Transport | BR/EDR RFCOMM — **not BLE** |
| Gadgetbridge | 0.95.1 (versionCode 255), upstream `master` at commit `6a322305` (2026-10-31) |

Firmware matters. The protocol findings below were established against
`20.1.0.114`; a different firmware may expose a different service and command
set. [`docs/reproduction.md`](docs/reproduction.md) explains how to tell.

---

## Quick start

```powershell
# 1. Get upstream at the exact baseline commit.
#    Do NOT use the 0.95.1 tag: the patch set was cut from master three weeks later,
#    and arrays.xml / strings.xml do not apply on the tag.
git clone https://codeberg.org/Freeyourgadget/Gadgetbridge.git
cd Gadgetbridge
git checkout 6a322305eae857436e77b3a0f5b3ebc438b047e9

# 2. Apply the patches
git apply --check /path/to/patches/all-changes.patch
git apply         /path/to/patches/all-changes.patch

# 3. Build (see docs/pitfalls.md for the Windows build quirks)
$env:JAVA_HOME         = '<jdk21>'
$env:GRADLE_USER_HOME  = '<gradle-home>'
$env:ANDROID_USER_HOME = '<android-home with the matching debug.keystore>'
tools\build-gb.ps1 -Project . -AndroidHome $env:ANDROID_USER_HOME

# 4. Install
tools\install-gb.ps1

# 5. Pair, then verify
#    docs/reproduction.md has the five-step acceptance check
```

Two details decide whether step 3 produces an installable APK:

- `ANDROID_USER_HOME` **must** contain the same `debug.keystore` as the build
  already on the phone, or installation fails with `signatures do not match`.
- On Windows, Gradle cannot delete directories under some paths. Renaming the
  module `build/` directories works where deleting them does not;
  `tools/build-gb.ps1` automates this retry loop.

---

## What you can extract

| Data | Cadence / size |
|---|---|
| Activity samples (steps, calories, distance) | ~3,000 rows per day |
| Heart rate | ~1,200 rows per night, 60 s cadence |
| SpO2 | ~100–200 rows per night, ~5 min cadence |
| Sleep stages (light / deep / REM) | 10–30 rows per night |
| Beat-to-beat PPG (`sleep_data.bin`) | 20,000–30,000 beats, 60–110 KB per night |
| Battery, workouts, user and device attributes | on change |

Export layout (written by the patched auto-export worker, to a directory the
user picks through SAF):

```
manifest-<yyyyMMdd-HHmmss>.json    schema 6: written last; per-file table, key, column dictionary, checksums
<kind>-<yyyyMMdd-HHmmss>.csv       incremental rows for one table (same stamp as its manifest)
raw-sleep_data.bin                 undecoded TruSleep blob, stable name, rewritten when it changes
raw-rri_<yyyyMMdd>.csv             beat-to-beat stream, one file per day
raw-capture_<yyyyMMdd>.csv         capture timeline (stream opened / closed / session start)
Gadgetbridge-<yyyyMMdd-HHmmss>.db  daily full snapshot (optional)
```

Manifests and CSVs older than 14 days are deleted by the exporter; the consumer
must never delete or write anything in this directory.

A downstream program only needs to read this directory. It must not import
Gadgetbridge classes — the file layout is the contract.

---

## Three findings worth the read

**1. Enabling TruSleep silently zeroes every sleep file.**

```
trusleep = true   →  sleep_state.bin = 0 bytes,  sleep_data.bin = 0 bytes
trusleep = false  →  sleep_state.bin = 32 bytes, sleep_data.bin = 105716 bytes
```

The watch switches to a `newSync` protocol that Gadgetbridge does not implement
for this device, and both files come back empty. The symptom looks like "sleep
data stopped updating"; the cause is a setting whose name suggests the opposite.

**2. The watch's Bluetooth stack can wedge.**

Gadgetbridge sits at "authenticating" indefinitely while the log shows
`read failed, socket might closed or timeout`. Bond and keys are intact.
Restarting the watch clears it immediately — no re-pairing, no reinstall.

**3. A probe can consume a file before the archiver sees it.**
The watch hands out each data file once. If a diagnostic request for
`sleep_data.bin` runs before the archive path, the archive gets zero bytes.
Exactly one consumer may request a given file.

Measured on 2026-11-14, after the probe sweep was switched off: this applies to the
**0x0A** path only. Over 0x2C the watch hands the same `sleep_data.bin` out again on
every sync (105716 bytes at 23:36:18, 23:36:25 and 23:36:28 of one connection), so a
lost 0x2C download is recoverable — waiting one sync is enough. The rule above stays
in place because it costs nothing to keep.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/protocol-findings.md`](docs/protocol-findings.md) | The core reference: 0x0A and 0x2C services, type-byte enumeration, capability map, TruSleep beat format, with evidence |
| [`docs/pitfalls.md`](docs/pitfalls.md) | Do / don't list — each entry gives symptom, cause, fix |
| [`docs/reproduction.md`](docs/reproduction.md) | What to replace, what must match, five-step acceptance test |
| [`docs/patches.md`](docs/patches.md) | Which patches are production-relevant and which are research scaffolding |
| [`docs/upstream-baseline.md`](docs/upstream-baseline.md) | The 0.95.1 baseline, what upstream already fixed, how to rebase |
| [`docs/watch-files.md`](docs/watch-files.md) | Files on the watch and what they contain |
| [`docs/pipeline.md`](docs/pipeline.md) | Analysis pipeline |
| [`docs/apnea-analysis.md`](docs/apnea-analysis.md) | Definitions and thresholds for the breathing-related metrics |
| [`docs/next-steps.md`](docs/next-steps.md) | Open work |
| [`docs/review-2026-11-14.md`](docs/review-2026-11-14.md) | Code review of the patch set: what was fixed, what still needs the watch |

The documents themselves are written in Chinese; the protocol tables, code and
commands in them are language-independent. An English translation is welcome as
a contribution.

---

## Repository layout

```
docs/       device notes, protocol findings, pitfalls, reproduction guide
patches/    local patch set (all-changes.patch is the combined diff)
tools/      PowerShell: build, install, guarded UI automation
decoders/   Python: TruSleep beat parser, CVHR and heart-rate surge analysis
```

---

## Scope and caveats

- **Not an AHI measurement.** The derived metrics (CVHR valleys, heart-rate
  surges) are physiological load indicators. They are not a diagnosis and must
  not be presented as one.
- **Not affiliated with the Gadgetbridge project.** Patches here are local
  research changes; they are not proposed for upstream in this form.
- **Single device.** Everything was validated on one watch and one phone. Your
  firmware may behave differently — the acceptance test in
  `docs/reproduction.md` is there to detect that early.
- Gadgetbridge is AGPL-3.0. Patches in this repository are derivative work and
  carry the same licence (see [`LICENSE`](LICENSE)). Nothing here is copied from another project.
