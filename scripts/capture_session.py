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
2. ``spectacle --background`` — KDE Plasma (e.g. Fedora KDE), Wayland or X11.
   KWin lets Spectacle capture without a permission prompt. It grabs the whole
   desktop in logical coordinates into a private temp dir; we crop to the
   region and DELETE the full-desktop original immediately. Monitors come from
   ``kscreen-doctor`` (names like DP-1, HDMI-A-2).
3. XDG desktop portal (``org.freedesktop.portal.Screenshot``) — GNOME Wayland.
   The portal grabs the full desktop to a temporary file; we immediately crop
   to the selected region and DELETE the full-screen original, so only the
   region ever persists. Requires a one-time permission grant (see
   ``--grant-portal-permission``).
4. X11 tools (``maim``/``scrot``/ImageMagick ``magick x:root``) — X11 sessions.
   Full-root grab cropped to the region in-memory before writing.

Privacy: only the selected region is written to the output directory. Select
a region covering ONLY the VTT window/monitor — never one containing Discord.

Output layout (``--output-dir``, default ``$SCREENSHOTS_DIR``, else
``$TEMP_DIR/screenshots``):

    session_start.txt      unix timestamp written once at startup
    shot_<unix_ts>.png     one cropped frame per kept capture

A new capture moves the frames of an earlier game (started over 12 h ago) to
``previous/``; restarting within 12 h resumes the same capture.

Frames nearly identical to the previous KEPT frame (mean absolute difference
of a 64x64 grayscale downscale below ``--dedupe-threshold``) are dropped.

Usage (start BEFORE the session, stop with Ctrl+C):

    ./run.sh capture                              # same as the line below
    python3 scripts/capture_session.py            # CAPTURE_MONITOR/CAPTURE_CROP from .env
    python3 scripts/capture_session.py --monitor LG --crop 2459x1342+100+98
    python3 scripts/capture_session.py --region 2560x1440+0+0 --interval 60

``--monitor`` matches a connector name (DP-1) or the monitor's EDID model
("LG" finds an "LG ULTRAGEAR+" on any port). ``--crop`` cuts a sub-region
out of the chosen monitor, in that monitor's own coordinates — e.g. only the
Foundry page inside a maximized Firefox, without the desktop panels, browser
toolbars, bookmarks bar and vertical-tabs column. Defaults for both come from
CAPTURE_MONITOR / CAPTURE_CROP in the repo .env.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNATURE_SIZE = 64  # downscale side for dedupe signatures
# A capture started longer ago than this belongs to an earlier game: its
# frames are moved aside instead of being mixed into the new session.
STALE_CAPTURE_SECS = 12 * 3600


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

    def sub_region(self, crop: Region) -> Region:
        """`crop` (in this region's own coordinates) as an absolute region."""
        if crop.x + crop.width > self.width or crop.y + crop.height > self.height:
            raise ValueError(f"Crop {crop} does not fit inside {self.width}x{self.height}.")
        return Region(crop.width, crop.height, self.x + crop.x, self.y + crop.y)

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


def _kscreen_monitors() -> list[tuple[str, Region]]:
    """KDE outputs from `kscreen-doctor -j` as (name, region) in logical coordinates.

    kscreen reports the mode size in physical pixels plus a scale factor; the
    desktop (and Spectacle's ``--scaled`` capture) uses logical pixels, so a
    4K output at scale 1.7 becomes 2259x1271 at its logical position.
    """
    tool = shutil.which("kscreen-doctor")
    if not tool:
        return []
    try:
        out = subprocess.run(
            [tool, "-j"], capture_output=True, text=True, timeout=10, check=True
        ).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        return []
    monitors: list[tuple[str, Region]] = []
    for output in data.get("outputs", []):
        if not (output.get("connected") and output.get("enabled")):
            continue
        size = output.get("size") or {}
        pos = output.get("pos") or {}
        width, height = size.get("width"), size.get("height")
        if not width or not height:
            continue
        if output.get("rotation") in (2, 8):  # rotated left/right
            width, height = height, width
        scale = float(output.get("scale") or 1.0)
        region = Region(
            round(width / scale), round(height / scale), int(pos.get("x", 0)), int(pos.get("y", 0))
        )
        monitors.append((str(output.get("name")), region))
    return sorted(monitors, key=lambda item: (item[1].x, item[1].y))


def edid_model(connector: str) -> str:
    """'<vendor code> <model>' from the connector's EDID (e.g. 'GSM LG ULTRAGEAR+'), or ''."""
    for edid_file in Path("/sys/class/drm").glob(f"card*-{connector}/edid"):
        try:
            edid = edid_file.read_bytes()
        except OSError:
            continue
        if len(edid) < 128:
            continue
        code = (edid[8] << 8) | edid[9]
        vendor = "".join(chr(((code >> shift) & 0x1F) + 64) for shift in (10, 5, 0))
        model = ""
        for offset in range(54, 126, 18):  # display descriptors; 0xFC = product name
            if edid[offset : offset + 3] == b"\0\0\0" and edid[offset + 3] == 0xFC:
                model = edid[offset + 5 : offset + 18].decode("ascii", "replace").strip()
        return f"{vendor} {model}".strip()
    return ""


def find_monitor(spec: str, monitors: list[tuple[str, Region]]) -> tuple[str, Region]:
    """Match `spec` against connector names (exact), then EDID vendor/model (substring)."""
    wanted = spec.strip().casefold()
    for name, region in monitors:
        if name.casefold() == wanted:
            return name, region
    matches = [(n, r) for n, r in monitors if wanted in edid_model(n).casefold()]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(f"{n} ({edid_model(n) or '?'})" for n, _ in monitors) or "none"
    problem = "matches several monitors" if matches else "not found"
    raise SystemExit(f"Monitor {spec!r} {problem}. Available: {available}")


def list_monitors() -> list[tuple[str, Region]]:
    """Connected monitors as (name, region): kscreen-doctor on KDE, else `xrandr`."""
    if _kde_session():
        monitors = _kscreen_monitors()
        if monitors:
            return monitors
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
            "No slurp and no monitors found (kscreen-doctor/xrandr). "
            "Pass --region WxH+X+Y explicitly."
        )
    print("Select the monitor showing the VTT (never the one with Discord!):")
    for i, (name, region) in enumerate(monitors, start=1):
        print(f"  [{i}] {name}  {region}  {edid_model(name)}")
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


class SpectacleBackend:
    """KDE Plasma via `spectacle --background` (no permission prompt under KWin).

    Spectacle writes the FULL desktop (logical coordinates, ``--scaled``, the
    same space as the kscreen-doctor monitor geometry) into a private 0700
    temp dir; we crop to the region and delete the original immediately, so
    nothing outside the region persists on disk.
    """

    name = "spectacle"

    def __init__(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="rpgnotes-capture-"))
        atexit.register(shutil.rmtree, self._tmpdir, ignore_errors=True)

    @staticmethod
    def available() -> bool:
        return _kde_session() and shutil.which("spectacle") is not None and _have_magick()

    def capture(self, region: Region, dest: Path) -> None:
        full = self._tmpdir / "desktop.png"
        try:
            proc = subprocess.run(
                [
                    "spectacle", "--background", "--nonotify", "--fullscreen",
                    "--scaled", "--output", str(full),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0 or not full.exists():
                raise CaptureError(
                    f"spectacle failed (exit {proc.returncode}): {proc.stderr.strip()}"
                )
            _magick(str(full), "-crop", region.magick_geometry, "+repage", str(dest))
        finally:
            full.unlink(missing_ok=True)  # never keep the full-desktop frame
        if not dest.exists():
            raise CaptureError("spectacle capture: crop produced no file")


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
        return _have_magick()

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


def _have_magick() -> bool:
    return shutil.which("magick") is not None or shutil.which("convert") is not None


def _kde_session() -> bool:
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    return "KDE" in desktops


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


def pick_backend() -> GrimBackend | SpectacleBackend | PortalBackend | X11Backend:
    if GrimBackend.available():
        return GrimBackend()
    if SpectacleBackend.available():
        return SpectacleBackend()
    if _kde_session() and _wayland_session():
        raise SystemExit(
            "KDE Wayland session, but Spectacle or ImageMagick is missing. Install them:\n"
            "  sudo dnf install spectacle ImageMagick"
        )
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
        "spectacle + ImageMagick (KDE Plasma), python3-dbus/python3-gi + "
        "ImageMagick (GNOME Wayland), or maim/scrot/ImageMagick (X11)."
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


def env_value(key: str) -> str:
    """`key` from the environment, else from the repo .env (first match), else ''."""
    value = os.environ.get(key, "")
    env_file = REPO_ROOT / ".env"
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                value = line.split("=", 1)[1].split(" #", 1)[0].strip().strip("'\"")
                break
    return value


def default_output_dir() -> Path:
    """`$SCREENSHOTS_DIR` (where the pipeline reads frames), else `$TEMP_DIR/screenshots`.

    Both are read from the repo .env; relative paths are taken from the repo root.
    """
    screenshots = env_value("SCREENSHOTS_DIR")
    path = (
        Path(screenshots).expanduser()
        if screenshots
        else Path(env_value("TEMP_DIR") or "temp").expanduser() / "screenshots"
    )
    return path if path.is_absolute() else REPO_ROOT / path


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------


def set_aside_previous_capture(output_dir: Path, *, fresh: bool) -> None:
    """Move an earlier game's frames to `previous/`; resume a recent capture.

    A capture restarted within STALE_CAPTURE_SECS (crash, reboot mid-game)
    continues in place. Otherwise the old frames go to `previous/` (replacing
    the one before), which the pipeline ignores — one game of backup in case
    it was not processed yet.
    """
    start_file = output_dir / "session_start.txt"
    frames = sorted(output_dir.glob("shot_*.png"))
    if not frames and not start_file.exists():
        return
    try:
        started: int | None = int(start_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        started = None
    if not fresh and started is not None and time.time() - started < STALE_CAPTURE_SECS:
        when = time.strftime("%d.%m %H:%M", time.localtime(started))
        print(f"Resuming the capture started {when} ({len(frames)} frames so far).")
        return
    previous = output_dir / "previous"
    shutil.rmtree(previous, ignore_errors=True)
    previous.mkdir()
    for path in [*frames, start_file]:
        if path.exists():
            path.rename(previous / path.name)
    print(f"Moved {len(frames)} frame(s) of the previous capture to {previous}.")


def run(args: argparse.Namespace) -> int:
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    backend = pick_backend()
    region = parse_region(args.region) if args.region else None
    if region is None and args.monitor:
        name, region = find_monitor(args.monitor, list_monitors())
        print(f"Monitor: {name} {edid_model(name)}".rstrip())
    if region is None:
        region = select_region_interactive()
    if args.crop:
        try:
            region = region.sub_region(parse_region(args.crop))
        except ValueError as e:
            raise SystemExit(f"Bad --crop: {e}") from e

    start_ts = int(time.time())
    start_file = output_dir / "session_start.txt"
    set_aside_previous_capture(output_dir, fresh=args.fresh)
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
        "--monitor",
        default=env_value("CAPTURE_MONITOR") or None,
        help=(
            "Monitor by connector name (DP-1) or EDID model substring (LG). "
            "Default: CAPTURE_MONITOR from .env."
        ),
    )
    parser.add_argument(
        "--crop",
        default=env_value("CAPTURE_CROP") or None,
        help=(
            "WxH+X+Y inside the chosen monitor/region (e.g. only the browser page). "
            "Default: CAPTURE_CROP from .env."
        ),
    )
    parser.add_argument(
        "--dedupe-threshold",
        type=float,
        default=4.0,
        help="Mean abs 0-255 gray diff below which a frame is dropped as unchanged.",
    )
    parser.add_argument("--once", action="store_true", help="Capture a single frame and exit.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Start a new capture even if the last one began less than "
            f"{STALE_CAPTURE_SECS // 3600} h ago (its frames move to previous/)."
        ),
    )
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
