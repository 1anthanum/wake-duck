"""macOS backends, using the `osascript` command that ships with the system.

* ``MacVolume``  - reads and sets the output volume of the default output device
  (``get volume settings`` / ``set volume output volume N``). These are Standard
  Additions commands and are not expected to trigger a permission prompt. The number
  is the slider's 0-100, which follows loudness as you hear it, not power.
* ``MacMusicApps`` - pauses and resumes Music and Spotify. It first asks whether the
  app is running, so it never launches one. The first pause triggers macOS's
  "Automation" permission prompt for whatever process runs your assistant.
  Apps that do not take AppleScript (many browser tabs, video calls) are not touched.

Both take a ``run`` argument: a function ``run(args) -> stdout``. The default runs
the command with a 2-second timeout and a minimal environment. The test suite
passes a fake ``run``; it never calls osascript.
"""
import subprocess


def default_run(args, timeout=2.0):
    out = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                         env={"PATH": "/usr/bin:/bin"})
    return out.stdout.strip()


def _osascript(run, script):
    return run(["osascript", "-e", script])


class MacVolume:
    def __init__(self, run=default_run):
        self.run = run

    def get_volume(self):
        out = _osascript(self.run, "get volume settings")
        vol, muted = None, False
        for part in out.split(","):
            key, _, value = part.strip().partition(":")
            value = value.strip()
            if key == "output volume":
                vol = int(value) if value.isdigit() else None   # "missing value" on devices without volume
            elif key == "output muted":
                muted = value == "true"
        return vol, muted

    def set_volume(self, value):
        _osascript(self.run, "set volume output volume %d" % _clamp_volume(value))


def _clamp_volume(value):
    return max(0, min(100, int(value)))


class MacMusicApps:
    APPS = ("com.apple.Music", "com.spotify.client")

    def __init__(self, run=default_run, apps=APPS):
        self.run = run
        self.apps = tuple(apps)

    def _tell(self, app, what):
        if app not in self.apps:
            raise ValueError("unknown app id")
        return _osascript(self.run, 'if application id "%s" is running then tell application id "%s" to %s'
                          % (app, app, what))

    def state(self, app):
        out = self._tell(app, "get player state as string")
        return out if out in ("playing", "paused", "stopped") else None

    def pause(self, app):
        self._tell(app, "pause")

    def play(self, app):
        self._tell(app, "play")
