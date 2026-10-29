# Development guidance

This repository is the public prerelease source for Whiteboxgrind Agent. Runtime data, target sources, recovered keys, personal authorizations and detailed research archives belong outside Git.

- Supported release target: Windows x64 + Codex local execution + Docker/WSL2, with the currently validated AES-128 C interfaces.
- Keep deployment paths configurable. Do not add personal absolute paths to tracked files.
- User execution procedures live in `plugins/whiteboxgrind/skills`. Preserve pilot decisions and terminal retention choices; tests cannot grant those choices for real runs.
- Regression tests use synthetic grants and disposable artifacts. A passing test or doctor result is not evidence of a new target's recovery.
- Build from fixed source/archive locks; changes to runtime code require a newly bound image and release manifest.
- Root MIT applies only to independently authored code. Preserve upstream notices, corresponding sources and derived-patch licenses.
- Keep original evidence immutable and distinguish local acceptance from clean-machine, real UI and public distribution acceptance.
- Public release requires an explicit user instruction; no automatic remote creation or publication.
