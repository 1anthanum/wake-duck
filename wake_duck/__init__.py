"""wake-duck: make room for a voice assistant when music is playing, and check the wake word twice.

    Ducker      - duck or pause the music when the wake word fires, put it back afterwards
    SecondGate  - confirm the wake word on the transcript before answering
    WakeRound   - glue for one round, including the retry window after a failed first try

Standard library only. Backends: wake_duck.backends.FakeSystem (in memory),
wake_duck.macos (osascript).
"""
from .ducker import DuckConfig, Ducker
from .gate import GateConfig, GateResult, SecondGate, normalize
from .round import WakeRound

__version__ = "0.1.0"
__all__ = ["DuckConfig", "Ducker", "GateConfig", "GateResult", "SecondGate", "WakeRound", "normalize", "__version__"]
