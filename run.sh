#!/usr/bin/env bash
# Thin wrapper: `./run.sh [args]` → docker compose run --rm rpgnotes [args]
# Examples:
#   ./run.sh                  # full workflow on newest session in DOWNLOADS_DIR
#   ./run.sh transcribe       # transcription only
#   ./run.sh manual           # manual entry
#   ./run.sh --menu           # legacy interactive menu
set -euo pipefail
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
exec docker compose run --rm rpgnotes "$@"
