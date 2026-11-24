"""Where the five calls go in a listener loop.

Runs as-is on fake events (`python examples/wire_up.py`): no microphone, no audio.
To use it for real, replace FakeSystem with the macOS backends (see the comments)
and feed it your own keyword-spotter and speech-to-text events.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wake_duck import DuckConfig, Ducker, GateConfig, SecondGate, WakeRound  # noqa: E402
from wake_duck.backends import FakeClock, FakeSystem  # noqa: E402

clock = FakeClock()
system = FakeSystem(volume=60)
# Real macOS:
#   from wake_duck.macos import MacVolume, MacMusicApps
#   volume, player, clock = MacVolume(), MacMusicApps(), time.monotonic
ducker = Ducker(volume=system, player=system, config=DuckConfig(mode="duck"), now=clock, wall=clock,
                memo_path=None, log=print)          # give it a file path to survive crashes
gate = SecondGate(GateConfig(names=["nova"], aliases=["noba"], lookalikes=["bossa nova", "casanova"]))
rnd = WakeRound(ducker, gate, retry_s=6.0, now=clock, log=print)
ducker.recover_on_start()                            # 1. once, at start-up


def speak(words):
    print("assistant:", words)


# Your loop gets events from your own audio stack; here they are scripted.
events = [
    (0.0, "wake", {"room_loud": True}),              # keyword spotter fired; your VAD says the room is loud
    (1.6, "sentence", {"text": "Nova, set a timer for ten minutes", "started": -0.3}),
    (2.5, "idle", {}),
]
for t, kind, data in events:
    clock.t = t
    if kind == "wake":
        rnd.first_gate(room_loud=data["room_loud"])  # 2. first gate
    elif kind == "sentence":
        result = rnd.utterance(data["text"], t_start=data["started"])   # 3. second gate
        if result.confirmed:
            rnd.speak(speak, "Timer set: " + result.rest.split("for", 1)[-1].strip())  # 4. speak through it
    elif kind == "idle":
        rnd.end()                                    # 5. round over (also call rnd.tick() every loop)
ducker.close()
print("final volume:", system.volume)
