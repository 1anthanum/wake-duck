"""Make room for the assistant: when the wake word fires while music is on, duck or pause it, then put it back.

Two modes:

* ``duck``  - lower the system output volume to ``duck_percent`` % of what it was
  (default 25 %, at least 1). Needs ``room_loud=True`` from your listener, because
  "an output stream is open" does not mean anything is audible.
* ``pause`` - ask the media apps the player backend knows about; pause the ones that
  are playing. Does not need ``room_loud``: a voice-activity detector often does not
  count music as "loud", so the player is asked directly.
* ``off``   - do nothing.

Put back, whichever comes first: the assistant is about to speak (duck mode only -
it usually shares the same output, so it would be ducked too), the round is over,
or a safety limit (``max_hold_s`` in duck mode, ``max_pause_s`` in pause mode).

Rules that came from living with it:

* If the person moved the volume while it was ducked (more than ``drift`` steps away
  from what we set), leave it alone - their choice wins.
* Resume only apps *we* paused, and only if they are still paused.
* At most one round per ``min_gap_s`` seconds, so a run of false wakes cannot pump
  the music. A round that changed nothing (the app ignored the pause) does not
  use up the gap.
* If the process dies while ducked, a small memo file lets the next start restore
  the volume - but only within ``stale_memo_s`` and only if the volume is still
  where we left it.

Nothing here starts threads or processes; backends do the real work. If your
backend is slow, call ``on_wake`` from a worker thread.
"""
import json
import os
import threading
import time
from dataclasses import dataclass


def _clamp(value, lo, hi):
    return min(hi, max(lo, value))


@dataclass
class DuckConfig:
    mode: str = "duck"          # "duck" | "pause" | "off"
    duck_percent: float = 25.0  # clamped to 5..80
    max_hold_s: float = 8.0     # duck mode: restore after this long no matter what
    max_pause_s: float = 600.0  # pause mode: resume after this long no matter what
    min_gap_s: float = 60.0     # at most one round per this many seconds
    drift: int = 2              # volume steps that still count as "untouched"
    settle_s: float = 0.3       # pause mode: wait this long before checking the app stopped
    stale_memo_s: float = 600.0 # crash memo older than this is ignored

    def __post_init__(self):
        if self.mode not in ("duck", "pause", "off"):
            raise ValueError("mode must be 'duck', 'pause' or 'off'")
        self.duck_percent = _clamp(float(self.duck_percent), 5.0, 80.0)


class Ducker:
    """Keeps at most one hold (ducked volume or paused apps) at a time."""

    def __init__(self, volume=None, player=None, config=None, now=time.monotonic,
                 wall=time.time, sleep=time.sleep, memo_path=None, log=None):
        self.volume = volume
        self.player = player
        self.config = config or DuckConfig()
        self.now, self.wall, self.sleep = now, wall, sleep
        self.memo_path = memo_path
        self.log = log or (lambda line: None)
        self.hold = None          # {"mode": "duck", "original": 50, "ducked": 13, "since": t} or
                                  # {"mode": "pause", "apps": [...], "since": t}
        self.last_round = None
        self.counts = {"held": 0, "restored": 0, "user_changed": 0, "too_soon": 0,
                       "nothing_playing": 0, "did_not_stop": 0}
        self._lock = threading.Lock()

    @property
    def holding(self):
        return self.hold is not None

    # ------------------------------------------------------------------ wake
    def on_wake(self, room_loud=False):
        """First gate fired. Returns what happened, as a short word."""
        with self._lock:
            mode = self.config.mode
            if mode == "off":
                return "off"
            if self.hold is not None:
                return "already_holding"
            t = self.now()
            if self.last_round is not None and t - self.last_round < self.config.min_gap_s:
                self.counts["too_soon"] += 1
                self.log("too soon after the last round (%.0f s gap), not touching the music" % self.config.min_gap_s)
                return "too_soon"
            try:
                if mode == "pause":
                    return self._pause(t)
                return self._duck(t, room_loud)
            except Exception as e:  # a broken backend must never break wake-up
                self.log("could not make room: %s" % type(e).__name__)
                return "error"

    def _duck(self, t, room_loud):
        if not room_loud:
            self.counts["nothing_playing"] += 1
            return "quiet"
        vol, muted = self.volume.get_volume()
        if vol is None or muted or vol <= 0:
            self.counts["nothing_playing"] += 1
            return "nothing_playing"
        target = max(1, int(vol * self.config.duck_percent / 100.0 + 0.5))
        if target >= vol:
            return "already_low"
        self.volume.set_volume(target)
        back, _ = self.volume.get_volume()
        self.hold = {"mode": "duck", "original": vol, "ducked": back if back is not None else target, "since": t}
        self.last_round = t
        self.counts["held"] += 1
        self._write_memo(self.hold)
        self.log("ducked: volume %d -> %d" % (vol, self.hold["ducked"]))
        return "ducked"

    def _pause(self, t):
        apps = [a for a in self.player.apps if self.player.state(a) == "playing"]
        if not apps:
            self.counts["nothing_playing"] += 1
            return "nothing_playing"
        for app in apps:
            self.player.pause(app)
        if self.config.settle_s > 0:
            self.sleep(self.config.settle_s)
        stopped = [a for a in apps if self.player.state(a) != "playing"]
        if not stopped:
            self.counts["did_not_stop"] += 1   # nothing changed: does not use up the gap
            self.log("asked %d app(s) to pause, still playing; leaving it" % len(apps))
            return "did_not_stop"
        self.hold = {"mode": "pause", "apps": stopped, "since": t}
        self.last_round = t
        self.counts["held"] += 1
        self.log("paused: %s" % ", ".join(stopped))
        return "paused"

    # --------------------------------------------------------------- restore
    def restore(self, reason="done"):
        """Put things back. Returns "restored", "resumed", "user_changed", "left_alone" or "not_holding"."""
        with self._lock:
            hold, self.hold = self.hold, None
            if hold is None:
                return "not_holding"
            try:
                if hold["mode"] == "pause":
                    resumed = [a for a in hold["apps"] if self.player.state(a) == "paused"]
                    for app in resumed:
                        self.player.play(app)
                    if not resumed:
                        self.log("%s; the app was changed by hand, leaving it" % reason)
                        return "left_alone"
                    self.counts["restored"] += 1
                    self.log("%s; resumed: %s" % (reason, ", ".join(resumed)))
                    return "resumed"
                cur, _ = self.volume.get_volume()
                self._write_memo(None)
                if cur is None or abs(cur - hold["ducked"]) > self.config.drift:
                    self.counts["user_changed"] += 1
                    self.log("%s; volume was changed by hand (now %s), leaving it" % (reason, cur))
                    return "user_changed"
                self.volume.set_volume(hold["original"])
                self.counts["restored"] += 1
                self.log("%s; volume back to %d" % (reason, hold["original"]))
                return "restored"
            except Exception as e:
                self.log("could not put things back: %s" % type(e).__name__)
                return "error"

    def before_speaking(self):
        """Call right before the assistant makes a sound. Duck mode restores first; pause mode keeps the music paused."""
        if self.hold is not None and self.hold["mode"] == "duck":
            return self.restore("assistant is about to speak")
        return None

    def wrap_speaker(self, speak):
        """Return a version of `speak` that calls before_speaking() first."""
        def wrapped(*args, **kwargs):
            self.before_speaking()
            return speak(*args, **kwargs)
        wrapped.__wrapped__ = speak
        return wrapped

    def tick(self, idle=False):
        """Call from your main loop. Restores when the listener is back to idle or a safety limit is reached."""
        hold = self.hold
        if hold is None:
            return None
        if idle:
            return self.restore("back to idle")
        limit = self.config.max_hold_s if hold["mode"] == "duck" else self.config.max_pause_s
        if self.now() - hold["since"] >= limit:
            return self.restore("held for %.0f s" % limit)
        return None

    def close(self):
        """Call on exit."""
        if self.hold is not None:
            return self.restore("exiting")
        return None

    # ----------------------------------------------------------- crash memo
    def _write_memo(self, hold):
        if not self.memo_path:
            return
        data = {} if hold is None else {"original": hold["original"], "ducked": hold["ducked"], "wall": self.wall()}
        tmp = self.memo_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.memo_path)
        except OSError:
            pass

    def recover_on_start(self):
        """Call once at start-up. If the last run died while ducked, restore - if it is recent and untouched."""
        if not self.memo_path:
            return None
        try:
            with open(self.memo_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        if not data or "original" not in data:
            return None
        self._write_memo(None)
        if self.wall() - float(data.get("wall", 0)) > self.config.stale_memo_s:
            return "too_old"
        cur, _ = self.volume.get_volume()
        if cur is None or abs(cur - int(data["ducked"])) > self.config.drift:
            return "user_changed"
        self.volume.set_volume(int(data["original"]))
        self.log("last run stopped while ducked; volume back to %d" % int(data["original"]))
        return "restored"
