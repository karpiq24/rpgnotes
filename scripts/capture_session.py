#!/usr/bin/env python3
"""Capture timestamped screenshots of a screen region during an RPG session.

Standalone companion to rpgnotes (Plan E, Tier 1). Stdlib only; the GNOME
portal backend additionally needs the distro `python3-dbus` + `python3-gi`
packages (present on stock Ubuntu). Safe to launch from the project venv:
on Wayland the script re-execs itself with the system python3 when the
portal modules are missing from the current interpreter.

Backends, auto-detected in this order:

1. ``grim`` (+ ``slurp`` for region selection) — wlroots Wayland compositors.
   Region-native capture; nothing outside the region is ever grabbed.
2. XDG desktop portal (``org.freedesktop.portal.Screenshot``) — GNOME Wayland.
   The portal grabs the full desktop to a temporary file; we immediately crop
   to the selected region and DELETE the full-screen original, so only the
   region ever persists. Requires a one-time permission grant (see
   ``--grant-portal-permission``).
3. X11 tools (``maim``/``scrot``/ImageMagick ``magick x:root``) — X11 sessions.
   Full-root grab cropped to the region in-memory before writing.

Privacy: only the selected region is written to the output directory. Select
a region covering ONLY the VTT window/monitor — never one containing Discord.

Output layout (``--output-dir``, default ``$DOWNLOADS_DIR/screens_session``):

    session_start.txt      unix timestamp written once at startup
    shot_<unix_ts>.png     one cropped frame per kept capture

Frames nearly identical to the previous KEPT frame (mean absolute difference
of a 64x64 grayscale downscale below ``--dedupe-threshold``) are dropped.

Usage (start BEFORE the session, stop with Ctrl+C):

    python3 scripts/capture_session.py            # pick monitor/region, go
    python3 scripts/capture_session.py --monitor DP-1
    python3 scripts/capture_session.py --region 2560x1440+0+0 --interval 60
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNATURE_SIZE = 64  # downscale side for dedupe signatures


# --------------------------------------------------------------------------
# Region
# --------------------------------------------------------------------------

_REGION_RE = re.compile(r"^(\d+)x(\d+)\+(\d+)\+(\d+)$")


@dataclass(frozen=True)
class Region:
    width: int
    height: int
    x: int
    y: int

    def __str__(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"

    @property
    def grim_geometry(self) -> str:
        return f"{self.x},{self.y} {self.width}x{self.height}"

    @property
    def magick_geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


def parse_region(spec: str) -> Region:
    match = _REGION_RE.match(spec.strip())
    if not match:
        raise ValueError(f"Region must look like WxH+X+Y (e.g. 2560x1440+0+0), got: {spec!r}")
    w, h, x, y = (int(g) for g in match.groups())
    if w <= 0 or h <= 0:
        raise ValueError(f"Region has non-positive size: {spec!r}")
    return Region(w, h, x, y)


def list_monitors() -> list[tuple[str, Region]]:
    """Parse `xrandr` connected outputs into (name, region) pairs."""
    xrandr = shutil.which("xrandr")
    if not xrandr:
        return []
    try:
        out = subprocess.run(
            [xrandr], capture_output=True, text=True, timeout=10, check=True
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    monitors: list[tuple[str, Region]] = []
    pattern = re.compile(r"^(\S+) connected(?: primary)? (\d+)x(\d+)\+(\d+)\+(\d+)", re.M)
    for m in pattern.finditer(out):
        name, w, h, x, y = m.group(1), *(int(g) for g in m.group(2, 3, 4, 5))
        monitors.append((name, Region(w, h, x, y)))
    return monitors


def select_region_interactive() -> Region:
    """Pick the region once at startup: slurp if present, else monitor menu."""
    if shutil.which("slurp"):
        print("Drag-select the VTT region with the mouse (slurp)…")
        out = subprocess.run(
            ["slurp", "-f", "%wx%h+%x+%y"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return parse_region(out)

    monitors = list_monitors()
    if not monitors:
        raise SystemExit(
            "No slurp and no xrandr monitors found. Pass --region WxH+X+Y explicitly."
        )
    print("Select the monitor showing the VTT (never the one with Discord!):")
    for i, (name, region) in enumerate(monitors, start=1):
        print(f"  [{i}] {name}  {region}")
    print(f"  [{len(monitors) + 1}] enter a custom region (WxH+X+Y)")
    while True:
        choice = input(f"Choice [1-{len(monitors) + 1}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(monitors):
            return monitors[int(choice) - 1][1]
        if choice.isdigit() and int(choice) == len(monitors) + 1:
            try:
                return parse_region(input("Region (WxH+X+Y): "))
            except ValueError as e:
                print(e)
                continue
        print("Invalid choice.")


# --------------------------------------------------------------------------
# Capture backends
# --------------------------------------------------------------------------


class CaptureError(RuntimeError):
    pass


class GrimBackend:
    """Region-native capture on wlroots compositors."""

    name = "grim"

    @staticmethod
    def available() -> bool:
        return os.environ.get("WAYLAND_DISPLAY") is not None and shutil.which("grim") is not None

    def capture(self, region: Region, dest: Path) -> None:
        proc = subprocess.run(
            ["grim", "-g", region.grim_geometry, str(dest)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0 or not dest.exists():
            raise CaptureError(f"grim failed: {proc.stderr.strip()}")


class PortalBackend:
    """GNOME Wayland via org.freedesktop.portal.Screenshot.

    The portal writes a FULL-desktop png to the user's Pictures dir; we crop
    to the region and delete the original immediately, so nothing outside the
    region persists on disk.
    """

    name = "xdg-portal"

    def __init__(self) -> None:
        import dbus  # type: ignore[import-not-found]
        from dbus.mainloop.glib import DBusGMainLoop  # type: ignore[import-not-found]
        from gi.repository import GLib  # type: ignore[import-not-found]

        DBusGMainLoop(set_as_default=True)
        self._glib = GLib
        self._dbus = dbus
        self._bus = dbus.SessionBus()
        portal = self._bus.get_object(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
        )
        self._iface = dbus.Interface(portal, "org.freedesktop.portal.Screenshot")
        self._counter = 0

    @staticmethod
    def available() -> bool:
        if not _wayland_session():
            return False
        try:
            import dbus  # noqa: F401
            from gi.repository import GLib  # noqa: F401
        except ImportError:
            return False
        return shutil.which("magick") is not None or shutil.which("convert") is not None

    @staticmethod
    def grant_permission() -> None:
        """One-time grant so the non-interactive portal call needs no dialog."""
        subprocess.run(
            [
                "dbus-send", "--session", "--print-reply",
                "--dest=org.freedesktop.impl.portal.PermissionStore",
                "/org/freedesktop/impl/portal/PermissionStore",
                "org.freedesktop.impl.portal.PermissionStore.SetPermission",
                "string:screenshot", "boolean:true", "string:screenshot",
                "string:", "array:string:yes",
            ],
            check=True,
            capture_output=True,
        )
        print("Portal screenshot permission granted (permission store: screenshot/screenshot).")

    def _full_screenshot(self) -> Path:
        dbus, GLib = self._dbus, self._glib
        self._counter += 1
        token = f"rpgnotescap{os.getpid()}n{self._counter}"
        sender = self._bus.get_unique_name()[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

        loop = GLib.MainLoop()
        result: dict[str, object] = {}

        def on_response(code: object, results: object) -> None:
            result["code"] = int(code)  # type: ignore[call-overload]
            with contextlib.suppress(KeyError, TypeError):
                result["uri"] = str(results["uri"])  # type: ignore[index]
            loop.quit()

        match = self._bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=handle,
        )
        try:
            self._iface.Screenshot(
                "",
                {
                    "handle_token": token,
                    "interactive": dbus.Boolean(False),
                    "modal": dbus.Boolean(False),
                },
            )
            GLib.timeout_add_seconds(25, loop.quit)
            loop.run()
        finally:
            match.remove()

        if result.get("code") != 0 or "uri" not in result:
            raise CaptureError(
                f"portal screenshot failed (response={result}). If this is the first run, "
                "run:  python3 scripts/capture_session.py --grant-portal-permission"
            )
        uri = str(result["uri"])
        if not uri.startswith("file://"):
            raise CaptureError(f"portal returned non-file uri: {uri}")
        from urllib.parse import unquote, urlparse

        return Path(unquote(urlparse(uri).path))

    def capture(self, region: Region, dest: Path) -> None:
        full = self._full_screenshot()
        try:
            _magick(str(full), "-crop", region.magick_geometry, "+repage", str(dest))
        finally:
            full.unlink(missing_ok=True)  # never keep the full-desktop frame
        if not dest.exists():
            raise CaptureError("portal capture: crop produced no file")


class X11Backend:
    """X11 sessions: maim (region-native) or scrot/magick full-root + crop."""

    name = "x11"

    @staticmethod
    def available() -> bool:
        if not os.environ.get("DISPLAY"):
            return False
        return any(shutil.which(t) for t in ("maim", "scrot", "magick", "import"))

    def capture(self, region: Region, dest: Path) -> None:
        if shutil.which("maim"):
            proc = subprocess.run(
                ["maim", "-g", region.magick_geometry, str(dest)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0 or not dest.exists():
                raise CaptureError(f"maim failed: {proc.stderr.strip()}")
            return
        # Full-root grab cropped in one ImageMagick pipeline; the full frame
        # never touches the disk.
        _magick(f"x:root[{region.magick_geometry}]", "+repage", str(dest))
        if not dest.exists():
            raise CaptureError("x11 magick capture produced no file")


def _magick(*args: str) -> None:
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        raise CaptureError("ImageMagick (magick/convert) not found")
    proc = subprocess.run([magick, *args], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise CaptureError(f"magick {' '.join(args[:2])}… failed: {proc.stderr.strip()}")


def _wayland_session() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


def _reexec_system_python_for_portal() -> None:
    """Re-exec with /usr/bin/python3 if it has the portal deps this one lacks.

    Venv interpreters don't see the distro python3-dbus/python3-gi packages,
    so a venv launch on GNOME Wayland would otherwise lose the portal backend.
    Does not return on success (process image is replaced).
    """
    if os.environ.get("_RPGNOTES_CAPTURE_REEXEC"):
        return
    sys_python = Path("/usr/bin/python3")
    # Do NOT compare resolved executable paths: a venv python is typically a
    # symlink to the system binary — what differs is site-packages, and the
    # probe below checks exactly that.
    if not sys_python.exists():
        return
    probe = subprocess.run(
        [str(sys_python), "-c", "import dbus, gi"], capture_output=True, timeout=30
    )
    if probe.returncode != 0:
        return
    os.environ["_RPGNOTES_CAPTURE_REEXEC"] = "1"
    os.execv(str(sys_python), [str(sys_python), str(Path(__file__).resolve()), *sys.argv[1:]])


def pick_backend() -> GrimBackend | PortalBackend | X11Backend:
    if GrimBackend.available():
        return GrimBackend()
    if _wayland_session():
        # NEVER fall back to X11 on Wayland: through XWayland it sees only
        # X11 apps (e.g. Discord) — native Wayland windows (Firefox/Foundry)
        # come out missing or transparent.
        if PortalBackend.available():
            return PortalBackend()
        _reexec_system_python_for_portal()
        raise SystemExit(
            "Wayland session, but the XDG portal backend is unavailable in this "
            f"interpreter ({sys.executable}): it needs the distro python3-dbus + "
            "python3-gi packages plus ImageMagick. Run with the system python:\n"
            "  /usr/bin/python3 scripts/capture_session.py\n"
            "(The X11 backend is disabled on Wayland — it can only see XWayland "
            "windows like Discord, not native windows like Firefox/Foundry.)"
        )
    if X11Backend.available():
        return X11Backend()
    raise SystemExit(
        "No usable screenshot backend found. Install grim+slurp (wlroots), "
        "ensure python3-dbus/python3-gi + ImageMagick (GNOME Wayland), or "
        "maim/scrot/ImageMagick (X11)."
    )


# --------------------------------------------------------------------------
# Dedupe
# --------------------------------------------------------------------------


def frame_signature(path: Path) -> bytes | None:
    """64x64 grayscale raw bytes of the frame, or None if extraction fails."""
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return None
    try:
        proc = subprocess.run(
            [
                magick, str(path),
                "-resize", f"{SIGNATURE_SIZE}x{SIGNATURE_SIZE}!",
                "-colorspace", "Gray", "-depth", "8", "GRAY:-",
            ],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    expected = SIGNATURE_SIZE * SIGNATURE_SIZE
    return proc.stdout if proc.returncode == 0 and len(proc.stdout) == expected else None


def mean_abs_diff(a: bytes, b: bytes) -> float:
    """Mean absolute per-pixel difference of two equal-length gray buffers (0-255)."""
    if len(a) != len(b) or not a:
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


# --------------------------------------------------------------------------
# Env / defaults
# --------------------------------------------------------------------------


def default_output_dir() -> Path:
    """`$DOWNLOADS_DIR/screens_session`, DOWNLOADS_DIR read from repo .env."""
    downloads = os.environ.get("DOWNLOADS_DIR", "")
    env_file = REPO_ROOT / ".env"
    if not downloads and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DOWNLOADS_DIR="):
                downloads = line.split("=", 1)[1].strip().strip("'\"")
                break
    base = Path(downloads).expanduser() if downloads else REPO_ROOT / "Downloads"
    if not base.is_absolute():
        base = REPO_ROOT / base
    return base / "screens_session"


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    backend = pick_backend()
    region = parse_region(args.region) if args.region else None
    if region is None and args.monitor:
        monitors = dict(list_monitors())
        if args.monitor not in monitors:
            raise SystemExit(
                f"Monitor {args.monitor!r} not found. Available: {', '.join(monitors) or 'none'}"
            )
        region = monitors[args.monitor]
    if region is None:
        region = select_region_interactive()

    start_ts = int(time.time())
    start_file = output_dir / "session_start.txt"
    if start_file.exists():
        print(f"Note: reusing existing {start_file} (resumed session).")
    else:
        start_file.write_text(f"{start_ts}\n", encoding="utf-8")

    print(f"Backend: {backend.name} | region: {region} | interval: {args.interval}s")
    print(f"Output: {output_dir}")
    print("Capturing… stop with Ctrl+C.")

    kept = dropped = failed = 0
    prev_signature: bytes | None = None
    stop = False

    def on_sigint(_sig: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_sigint)
    signal.signal(signal.SIGTERM, on_sigint)

    while not stop:
        ts = int(time.time())
        dest = output_dir / f"shot_{ts}.png"
        try:
            backend.capture(region, dest)
        except CaptureError as e:
            failed += 1
            print(f"[{time.strftime('%H:%M:%S')}] capture failed: {e}", file=sys.stderr)
        else:
            signature = frame_signature(dest)
            if (
                prev_signature is not None
                and signature is not None
                and mean_abs_diff(signature, prev_signature) < args.dedupe_threshold
            ):
                dest.unlink(missing_ok=True)
                dropped += 1
                print(f"[{time.strftime('%H:%M:%S')}] dropped (unchanged) — kept {kept}, dropped {dropped}")
            else:
                kept += 1
                if signature is not None:
                    prev_signature = signature
                print(f"[{time.strftime('%H:%M:%S')}] kept {dest.name} — kept {kept}, dropped {dropped}")

        if args.once:
            break
        # Sleep in 1s slices so Ctrl+C reacts promptly.
        for _ in range(args.interval):
            if stop:
                break
            time.sleep(1)

    elapsed = int(time.time()) - start_ts
    print(
        f"\nSession capture done: {kept} kept, {dropped} dropped, {failed} failed "
        f"in {elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}. "
        f"Frames in {output_dir}"
    )
    return 0 if (kept > 0 or args.once is False) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Interval screenshot capture of a screen region for rpgnotes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=600,
        help=(
            "Seconds between capture attempts. D&D scenes change slowly, and each "
            "kept frame costs a Gemini caption call at ingestion — 10 minutes is "
            "plenty. Near-identical frames are still dropped on the spot (and "
            "again at ingestion)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir(),
        help="Where shot_<ts>.png files land.",
    )
    parser.add_argument(
        "--region", help="Capture region as WxH+X+Y (skips interactive selection)."
    )
    parser.add_argument(
        "--monitor", help="Capture a whole monitor by xrandr name (e.g. DP-1)."
    )
    parser.add_argument(
        "--dedupe-threshold",
        type=float,
        default=4.0,
        help="Mean abs 0-255 gray diff below which a frame is dropped as unchanged.",
    )
    parser.add_argument("--once", action="store_true", help="Capture a single frame and exit.")
    parser.add_argument(
        "--grant-portal-permission",
        action="store_true",
        help="One-time: allow silent portal screenshots on GNOME Wayland, then exit.",
    )
    args = parser.parse_args(argv)

    if args.grant_portal_permission:
        PortalBackend.grant_permission()
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
