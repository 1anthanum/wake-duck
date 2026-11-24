"""What the library needs from the operating system, and an in-memory stand-in.

A *volume* backend has two methods:

    get_volume() -> (int | None, bool)   # output volume 0-100 (None = unreadable), muted?
    set_volume(value: int) -> None

A *player* backend knows a few media apps by id:

    apps: tuple of app ids it can see
    state(app) -> "playing" | "paused" | "stopped" | None   # None = not running / unknown
    pause(app) -> None
    play(app) -> None

`FakeSystem` implements both. Tests and the demo use it; nothing here touches
real audio. `wake_duck.macos` has the real macOS versions.
"""


class FakeSystem:
    """One output volume plus a few media apps, all in memory. Every change is logged in `actions`."""

    def __init__(self, volume=50, muted=False, apps=None, ignores_pause=()):
        self.volume = volume
        self.muted = muted
        self.readable = True                      # False -> get_volume() returns (None, False)
        self._state = dict(apps or {})            # {"music": "playing", ...}
        self.apps = tuple(self._state)
        self.ignores_pause = set(ignores_pause)   # apps that ignore a pause request
        self.actions = []

    # -- volume backend --
    def get_volume(self):
        if not self.readable:
            return None, False
        return self.volume, self.muted

    def set_volume(self, value):
        self.actions.append(("set_volume", int(value)))
        self.volume = int(value)

    # -- player backend --
    def state(self, app):
        return self._state.get(app)

    def pause(self, app):
        self.actions.append(("pause", app))
        if app not in self.ignores_pause and self._state.get(app) == "playing":
            self._state[app] = "paused"

    def play(self, app):
        self.actions.append(("play", app))
        if self._state.get(app) in ("paused", "stopped"):
            self._state[app] = "playing"

    # -- for scripts: things a person does by hand --
    def user_sets_volume(self, value):
        self.volume = int(value)

    def user_sets_state(self, app, state):
        self._state[app] = state


class FakeClock:
    """A clock you move by hand. Call it to read the time."""

    def __init__(self, t=0.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t

    def sleep(self, seconds):
        self.t += seconds
