#!/usr/bin/env bash
# rpgnotes launcher — the one command you need.
#
#   ./run.sh capture        during the game: Foundry screenshots (Ctrl+C to stop)
#   ./run.sh                after the game: shows the session it found, asks what to do
#   ./run.sh status         just show what it found and how far it got
#   ./run.sh full           transcribe + AI notes, no questions (also: transcribe)
#   ./run.sh full --fresh   same, but redo the session from scratch instead of resuming
#
# Everything except `capture` runs in the container (docker or Podman); the
# image is rebuilt when the code changed. `docker compose run --rm rpgnotes
# [args]` works too — this script adds the checks and a quieter build.
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "capture" ]]; then
  shift
  exec python3 scripts/capture_session.py "$@"
fi

die() { echo "✗ $*" >&2; exit 1; }

[[ -f .env ]] || die "No .env yet. Run: cp .env.example .env — then set GEMINI_API_KEY in it."

# KEY's value from .env (first match, quotes and trailing comment stripped).
env_value() {
  sed -n "s/^$1=//p" .env | head -n 1 | sed -e 's/[[:space:]]#.*//' -e "s/^[\"']//" -e "s/[\"']$//"
}

# Podman refuses to start with a missing bind-mount source. Create the dirs this
# project owns; for the ones pointing elsewhere a missing path means a typo.
screenshots=$(env_value SCREENSHOTS_DIR)
mkdir -p temp models "${screenshots:-temp/screenshots}"
for spec in DOWNLOADS_DIR:./Downloads OUTPUT_DIR:./output; do
  key=${spec%%:*}
  dir=$(env_value "$key")
  if [[ -z $dir || $dir == "${spec#*:}" ]]; then
    mkdir -p "${spec#*:}"
  elif [[ ! -d $dir ]]; then
    die "$key=$dir in .env does not exist."
  fi
done
context=$(env_value CAMPAIGN_CONTEXT_FILE)
if [[ -n $context && ! -f $context ]]; then
  die "CAMPAIGN_CONTEXT_FILE=$context in .env does not exist. Create it in the wiki:
  uv run python scripts/export_context.py   (or leave CAMPAIGN_CONTEXT_FILE empty to run without)"
fi

export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

if docker image inspect rpgnotes:latest >/dev/null 2>&1; then
  echo "Updating the container image…"
  if ! docker compose build rpgnotes >temp/build.log 2>&1; then
    tail -n 30 temp/build.log >&2
    die "Image build failed. Full log: temp/build.log"
  fi
else
  echo "First run: building the container image (downloads the ROCm base image, several GB)…"
  docker compose build rpgnotes
fi

exec docker compose run --rm rpgnotes "$@"
