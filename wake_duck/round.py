"""One wake-up round: first gate -> make room -> second gate -> answer or give up -> put the music back.

The part that is easy to get wrong is the failed first try. Music is loud, the
person says the name, the first gate fires and the music goes down - but the
sentence was half drowned out, so the second gate says no. If the music comes
straight back, the second try is just as drowned out as the first.

So after a failed second gate the round waits ``retry_s`` seconds (default 6)
with the music still down. If the first gate fires again in that window, it is
the same round: no new duck, and it does not count against ``min_gap_s``. If
nobody calls again, the music comes back.

States: ``idle`` -> ``armed`` (first gate fired, waiting for the sentence)
-> ``active`` (second gate passed) or ``retry`` (failed, music still down) -> ``idle``.
"""
import time

from .gate import GateResult


class WakeRound:
    def __init__(self, ducker, gate, retry_s=6.0, now=time.monotonic, log=None):
        self.ducker = ducker
        self.gate = gate
        self.retry_s = max(0.0, float(retry_s))
        self.now = now
        self.log = log or (lambda line: None)
        self.state = "idle"
        self.t_wake = None
        self.retry_until = None
        self.retries = 0

    def first_gate(self, room_loud=False):
        """The keyword spotter fired. Returns what the ducker did, or "retry" inside the retry window."""
        t = self.now()
        if self.state == "retry":
            self.state, self.t_wake, self.retry_until = "armed", t, None
            self.retries += 1
            self.log("called again within %.0f s: same round, music stays down" % self.retry_s)
            return "retry"
        if self.state in ("armed", "active"):
            self.t_wake = t
            return "already_awake"
        self.state, self.t_wake = "armed", t
        return self.ducker.on_wake(room_loud)

    def utterance(self, text, t_start, strict=None):
        """The sentence the first gate fired in is finished and transcribed."""
        if self.state != "armed":
            return GateResult("rejected", "not_armed")
        result = self.gate.check(text, t_start, self.t_wake, strict)
        if result.confirmed:
            self.state = "active"
            return result
        if self.ducker.holding and self.retry_s > 0:
            self.state, self.retry_until = "retry", self.now() + self.retry_s
            self.log("second gate said no (%s); waiting %.0f s for another call" % (result.why, self.retry_s))
        else:
            self.state = "idle"
            self.ducker.restore("second gate said no")
        return result

    def speak(self, speak, *args, **kwargs):
        """Say something during the round (restores first in duck mode)."""
        self.ducker.before_speaking()
        return speak(*args, **kwargs)

    def end(self):
        """The round is over (answer given, or the listener timed out)."""
        self.state, self.retry_until = "idle", None
        return self.ducker.restore("round over")

    def tick(self):
        """Call from the main loop."""
        if self.state == "retry" and self.now() >= self.retry_until:
            self.state, self.retry_until = "idle", None
            return self.ducker.restore("no second call within %.0f s" % self.retry_s)
        return self.ducker.tick(idle=False)
