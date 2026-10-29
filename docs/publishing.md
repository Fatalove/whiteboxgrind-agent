# Release maintenance

Assemble the Windows bundle using `scripts/release/prepare_release.ps1`, then pack the immutable allowlist with `pack_release.ps1`. Corresponding engine sources, patches and upstream notices must accompany the image. Never package private case/state/archive directories.

Generate the repository-only `plugins/whiteboxgrind/scripts/release-source.json` after hashing the final ZIP. It is intentionally excluded from the bundle to avoid embedding its own SHA256. Upload the ZIP and SHA256SUMS.txt to the matching GitHub prerelease, then run the Publish image workflow with that release tag.

The workflow verifies the ZIP, loaded image layers and engine/version labels, runs the regression suite in the released image, and publishes GHCR with a repository-scoped GITHUB_TOKEN. Review package visibility and verify anonymous access separately. Never publish personal credentials or copy a token into the repository.

Keep RC status until real clean-Windows installation is accepted. Do not promote prior local evidence to clean-machine or public-install evidence.
