# Disposable Linux compatibility checks

Use this standalone Compose file; do not combine it with upstream's port-publishing
files or make targets. The source image contains only the built package and two
explicit test scripts. Rendered configuration must have no ports or volumes,
network_mode none, user 1000:1000, read_only true, dropped capabilities and resource
limits. Tests create synthetic collections under container tmpfs, then discard
them. There is no HTTP listener, Qt main window, real profile or host registration.
MCP memory streams exercise actual serialization and tool dispatch on one thread.

```sh
PYTHON=.venv/bin/python bash package.sh
# Use the actual short revision, appending -dirty when any input is uncommitted.
export COMPANION_REVISION="$(git rev-parse --short HEAD)"
if test -n "$(git status --porcelain)"; then COMPANION_REVISION="$COMPANION_REVISION-dirty"; fi
docker compose -f tests/isolated/compose.yaml config --format json
docker compose -f tests/isolated/compose.yaml build
docker compose -f tests/isolated/compose.yaml run --rm --no-deps compatibility
docker compose -f tests/isolated/compose.yaml run --rm --no-deps compatibility python /artifact/synthetic_collection.py addon
docker compose -f tests/isolated/compose.yaml run --rm --no-deps compatibility python /artifact/synthetic_collection.py 124672614
```

Build installs aqt==26.9.2, typing-extensions==4.16.0 and the built vendor
pydantic version. This is an explicit Linux compatibility environment, not an
exact reconstruction of the installed Mac bundle. Capture pip freeze, built
archive SHA-256, image ID, source revision and dirty status with each result.
Both import-smoke and synthetic operations passed. Initial harness failures were
copied-file permissions, missing libgssapi runtime, no passwd entry for UID 1000,
and an unsupported FastMCP version constructor argument; all were corrected.
The upstream app_will_close hook is absent in this Anki and its existing fallback
warning remains; profile_will_close is present. No real Anki instance was restarted.
