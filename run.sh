#!/usr/bin/env bash
# Thin wrapper: `./run.sh [args]` → rebuild image, then
# docker compose run --rm rpgnotes [args]
# Examples:
#   ./run.sh                  # full workflow on newest session in DOWNLOADS_DIR
#   ./run.sh transcribe       # transcription only
#   ./run.sh manual           # manual entry
#   ./run.sh --menu           # legacy interactive menu
#
# This wrapper is optional: `docker compose run --rm rpgnotes [args]` works the
# same way. docker/entrypoint.sh auto-detects the host user and GPU device GIDs
# at startup. Exporting HOST_UID/HOST_GID here just makes ownership detection
# exact (skips the bind-mount heuristic) when you go through this script.
set -euo pipefail
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
docker compose build rpgnotes
exec docker compose run --rm rpgnotes "$@"
