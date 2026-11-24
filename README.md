# wake-duck

Two small pieces for a local voice assistant, with no dependencies beyond the Python standard library:

- **Make room for the assistant.** When the wake word fires while music is playing, duck the system volume (or pause the music app), and put it back when the round is over, without overriding anyone who touched the volume in between.
- **Check the wake word twice.** A loose keyword spotter only lights the light. The assistant answers only if the finished sentence starts with its name. If the first try fails, the music stays down for a few seconds so the second try can be heard.

v0.1. Rewritten from a private home voice-assistant project; every example here is made up. Python 3.9+. MIT.

## Quick start

```
python -m wake_duck demo              # scripted walk-through on a fake system: nothing real is touched
python -m unittest discover -s tests  # 36 tests, all on fakes
python examples/wire_up.py            # where the five calls go in a listener loop
```

`pip install .` also gives you a `wake-duck` command (`wake-duck demo`, `wake-duck --version`).

The demo output is checked in as [`examples/demo-output.txt`](examples/demo-output.txt), and a test fails if it drifts.

## How it fits into a listener

```python
from wake_duck import Ducker, DuckConfig, SecondGate, GateConfig, WakeRound
from wake_duck.macos import MacVolume, MacMusicApps

ducker = Ducker(volume=MacVolume(), player=MacMusicApps(), config=DuckConfig(mode="duck"),
                memo_path="/path/to/wake-duck-memo.json")
gate = SecondGate(GateConfig(names=["nova"], aliases=["noba"], lookalikes=["bossa nova", "casanova"]))
rnd = WakeRound(ducker, gate, retry_s=6.0)

ducker.recover_on_start()                    # once at start-up
rnd.first_gate(room_loud=vad_says_loud)      # your keyword spotter fired
result = rnd.utterance(text, t_start)        # that sentence is finished and transcribed
if result.confirmed:
    rnd.speak(tts.say, answer_for(result.rest))
rnd.end()                                    # round over; also call rnd.tick() every loop
```

`t_start` and the moment `first_gate` is called have to come from the same clock (`time.monotonic` by default).

## What it does

### Making room (`Ducker`)

| | default | |
|---|---|---|
| `mode` | `duck` | `duck` lowers the system volume · `pause` pauses known media apps · `off` |
| `duck_percent` | 25 | duck to this % of the current volume (5–80), never below 1. 50 becomes 13 |
| when to duck | | only if `room_loud=True` and the output is not muted or at 0 |
| when to pause | | if a known app reports `playing`. `room_loud` is not needed, because voice-activity detectors often don't count music as loud |
| put back | | before the assistant speaks (duck mode only, since it usually shares the output) · round over · back to idle · `max_hold_s` 8 (duck) / `max_pause_s` 600 (pause) |
| `drift` | 2 | if the volume moved more than this while ducked, the person changed it: leave it |
| resume | | only apps we paused, and only if they are still paused |
| `min_gap_s` | 60 | at most one round per minute, so a run of false wakes can't pump the music. A round that changed nothing (the app ignored the pause) doesn't count |
| crash memo | | `memo_path` set: if the process died while ducked, the next start restores, but only within `stale_memo_s` (600) and only if the volume wasn't touched |

### The second gate (`SecondGate`)

The sentence passes if:

- the name (or an alias for how your speech-to-text misspells it) starts within the first `head_chars` (8) letters after normalisation (NFKC, case-folded, letters and digits only, so "um, hey Nova" works, and so do other scripts);
- it is not inside a look-alike you list (`"bossa nova"` is not a call; `"Nova, play some bossa nova"` is);
- or, if the text has no name, an optional stricter re-check you pass in says yes (for example the same spotter at a higher threshold).

If the spotter fired more than `lead_s` (2 s) after the sentence started and the name is not at the head, the name was said mid-sentence, and that is not a call. `result.rest` is what came after the name.

### One round (`WakeRound`)

`idle → armed → active`, or `armed → retry → idle`. After a failed second gate, the round waits `retry_s` (6 s) with the music still down. A second call in that window belongs to the same round: no new duck, and no use of the 60 s gap. `retry_s=0` puts the music back at once.

## macOS backends

`wake_duck.macos` talks to `osascript`, which ships with macOS:

- `MacVolume`: `get volume settings` / `set volume output volume N` on the default output device. These are Standard Additions commands and are not expected to trigger a permission prompt.
- `MacMusicApps`: Music and Spotify, `pause` / `play` / `player state`. It checks `is running` first, so it never launches an app. The first pause triggers macOS's Automation permission prompt for whatever process runs your assistant.

Both take a `run` function, so you can swap in your own. The tests use a fake one and never run a command. On other systems, write the two small backends described in [`wake_duck/backends.py`](wake_duck/backends.py).

## Limits

- Ducking only lowers this computer's output. A TV or another speaker in the room is not affected; the duck still happens and is put back within 8 s.
- "An output stream is open" does not mean sound is coming out, so duck mode relies on your own `room_loud` signal. If that signal misses quiet music, nothing is ducked.
- The volume number is the slider position (0–100), which follows perceived loudness: 25 % of the slider is not 25 % of the power.
- Apps that don't take AppleScript (many browser tabs, video calls) are not paused.
- If the process is killed hard while ducked, nothing restores until the next start, and only within 10 minutes.
- This library does not do wake-word detection, voice activity detection or speech-to-text. You bring those; it decides what to do with their events.

## License

MIT, see [LICENSE](LICENSE). No third-party code, models or data.
