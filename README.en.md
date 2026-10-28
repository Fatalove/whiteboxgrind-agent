# Whiteboxgrind Agent

A local Codex plugin and command-line workflow for supported AES-128 C white-box targets, built around the Whiteboxgrind analysis toolchain.

**0.3.0-rc.1 is a local release candidate. Public download URLs and clean-Windows acceptance are pending.** GitHub publication has not happened.

The supported launch target is Windows x64, local Codex execution, and Docker Desktop with WSL2. The workflow checks dependencies, prepares a task, runs a pilot, waits for a human decision before formal collection, and exports independently checked results next to the input. Arbitrary binaries, algorithms, and unfamiliar interfaces are outside this release's support.

See the [Chinese user guide](README.md) for installation, commands and troubleshooting. The plugin is under `plugins/whiteboxgrind`, with a repository marketplace under `.agents/plugins`. Until publication, use a trusted offline ZIP and its SHA256 with the plugin's `scripts/bootstrap.ps1`; do not invent a release URL.

Each task contains `input`, a generated `task.json`, and separate `output` directories. `recovery.json` labels an AES-128 master-key candidate as hexadecimal and distinguishes a candidate from a verified result. Verification uses 16 disjoint holdout pairs; it is empirical evidence, not a proof of equivalence for all inputs. A recovered key is not automatically a competition flag.

All terminal outcomes ask for a retention decision. No answer means keep everything. Detailed research records, target sources, recovered keys, runtime state and virtual disks stay outside Git. Original independent code is MIT licensed; upstream components and derived patches retain their respective licenses. See [third-party notices](THIRD_PARTY_NOTICES.md).
