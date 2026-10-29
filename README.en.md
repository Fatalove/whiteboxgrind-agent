# Whiteboxgrind Agent

Local Codex automation for compatible AES-128 C targets, using Whiteboxgrind in Docker Desktop/WSL2 on Windows x64.

**0.3.0-rc.1 is a prerelease.** A real clean-Windows first installation remains unverified; see [acceptance limits](docs/validation.md).

1. Add `https://github.com/Fatalove/whiteboxgrind-agent.git` as a plugin marketplace in Codex.
2. Install `whiteboxgrind@whiteboxgrind-local`, open a new chat, and invoke `whiteboxgrind-setup`.
3. Select tool/data/software locations. The pinned release descriptor downloads and checks the bundle. No host Python is required.
4. Put target materials in a case's `input/`; ask `whiteboxgrind-analyze` to prepare it. A full pilot precedes your decision on formal collection.
5. Read `output/<run>/report.md`, `recovery.json`, and independent verification. Choose retention after completion; no reply retains everything.

[Windows bundle and checksums](https://github.com/Fatalove/whiteboxgrind-agent/releases/tag/v0.3.0-rc.1) · Container: `ghcr.io/fatalove/whiteboxgrind-agent:0.3.0-rc.1` (`linux/amd64`). The Windows bundle already includes the locked image and corresponding source/license materials. Docker Desktop is downloaded from its official source when needed and is not redistributed.

Only the supported AES-128 pointer interfaces are accepted. A verified AES master key is 16 bytes (32 hex characters), not automatically a challenge flag. No recovery guarantee is made for unknown targets. Historical runs and real keys stay outside Git.

[中文完整指南](README.md) · [Setup](docs/setup.md) · [Tasks and results](docs/tasks.md) · [License boundaries](THIRD_PARTY_NOTICES.md)
