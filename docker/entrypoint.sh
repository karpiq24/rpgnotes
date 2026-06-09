#!/usr/bin/env bash
# Self-configuring entrypoint so `docker compose run rpgnotes` works on any
# machine with no wrapper script and no host-specific env. It starts as root,
# detects everything host-specific from inside the container, then drops
# privileges to the host user.
#
# Two things differ per host and cannot be hard-coded:
#   1. The host user's UID/GID (so output files aren't owned by root).
#   2. The numeric GIDs that own /dev/kfd and /dev/dri/* — the same-named
#      render/video groups get different numbers on every system, so adding
#      them by name fails with "Unable to open /dev/kfd: Permission denied".
set -euo pipefail

# --- Target (host) user --------------------------------------------------
# Honor HOST_UID/HOST_GID if provided; otherwise infer from a bind-mounted
# directory, which carries its host owner's UID/GID into the container.
TARGET_UID="${HOST_UID:-}"
TARGET_GID="${HOST_GID:-}"
if [ -z "$TARGET_UID" ]; then
  for ref in /data/temp /data/output /data/context /data/downloads; do
    u="$(stat -c '%u' "$ref" 2>/dev/null)" || continue
    if [ "$u" != 0 ]; then
      TARGET_UID="$u"
      TARGET_GID="$(stat -c '%g' "$ref")"
      break
    fi
  done
fi
TARGET_UID="${TARGET_UID:-0}"
TARGET_GID="${TARGET_GID:-0}"

# --- GPU device groups ---------------------------------------------------
# Collect the GIDs that actually own the passed-through device nodes and add
# them numerically (their names don't match inside the container).
DEV_GIDS=""
for dev in /dev/kfd /dev/dri/renderD128 /dev/dri/card1; do
  [ -e "$dev" ] && DEV_GIDS="$DEV_GIDS,$(stat -c '%g' "$dev")"
done
DEV_GIDS="${DEV_GIDS#,}"

# --- Heal ownership of writable mounts -----------------------------------
# Fixes root-owned leftovers so the app (running as the host user) can write.
if [ "$TARGET_UID" != 0 ]; then
  for d in /data/output /data/temp /data/models; do
    [ -d "$d" ] && chown -R "$TARGET_UID:$TARGET_GID" "$d" 2>/dev/null || true
  done
fi

# --- Run -----------------------------------------------------------------
# If compose pinned a non-root `user:`, we can't change ids — just exec.
if [ "$(id -u)" != 0 ]; then
  exec python3 -m rpgnotes "$@"
fi

exec setpriv --reuid "$TARGET_UID" --regid "$TARGET_GID" \
  --groups "$TARGET_GID${DEV_GIDS:+,$DEV_GIDS}" \
  python3 -m rpgnotes "$@"
