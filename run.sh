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

# Session packages that are complete but not in the wiki yet (or changed since
# their import): with WIKI_DIR set, stage each one there and push it, so the
# draft waits on every workstation. No session note is created: /import-session
# does that later.
push_to_wiki() {
  local wiki outbox
  wiki=$(env_value WIKI_DIR)
  [[ -n $wiki ]] || return 0
  [[ -f $wiki/scripts/import_session.py ]] || { echo "✗ WIKI_DIR=$wiki has no scripts/import_session.py" >&2; return 1; }
  outbox=$(realpath "$(env_value OUTPUT_DIR)" 2>/dev/null || realpath output)
  python3 - "$outbox" <<'PY' | while read -r number; do
import json, pathlib, sys
for folder in sorted(pathlib.Path(sys.argv[1]).glob("[0-9][0-9][0-9]")):
    manifest, marker = folder / "manifest.json", folder / ".imported"
    try:
        complete = json.loads(manifest.read_text(encoding="utf-8")).get("complete")
    except (OSError, ValueError):
        continue
    if complete and (not marker.exists() or marker.stat().st_mtime < manifest.stat().st_mtime):
        print(int(folder.name))
PY
    echo "Wiki: staging session $number in $wiki and pushing it…"
    (cd "$wiki" && uv run python scripts/import_session.py "$number" --stage --push --outbox "$outbox") \
      || echo "✗ Wiki import of session $number failed; run it by hand: cd $wiki && uv run python scripts/import_session.py $number --stage --push" >&2
  done
}

status=0
docker compose run --rm rpgnotes "$@" || status=$?
case "${1:-menu}" in
  menu|full|--fresh) [[ $status -eq 0 ]] && push_to_wiki ;;
esac
exit $status
