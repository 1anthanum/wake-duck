"""A scripted walk-through on a fake system: fake clock, fake volume, fake music apps, made-up sentences.

Run it with ``python -m wake_duck demo``. Nothing real is touched: no audio, no
microphone, no apps. The same output is checked into examples/demo-output.txt
and a test makes sure it stays current.
"""
from .backends import FakeClock, FakeSystem
from .ducker import DuckConfig, Ducker
from .gate import GateConfig, SecondGate
from .round import WakeRound

GATE = GateConfig(names=["nova"], aliases=["noba", "knova"],
                  lookalikes=["bossa nova", "casanova", "supernova", "nova scotia"])


class _Printer:
    def __init__(self, clock, out):
        self.clock, self.out = clock, out

    def __call__(self, line):
        self.out.append("[t=%6.1fs] %s" % (self.clock(), line))


def _setup(mode, out, **system):
    clock = FakeClock()
    sysm = FakeSystem(**system)
    say = _Printer(clock, out)
    ducker = Ducker(volume=sysm, player=sysm, config=DuckConfig(mode=mode), now=clock, wall=clock,
                    sleep=clock.sleep, log=lambda line: say("  ducker: " + line))
    rnd = WakeRound(ducker, SecondGate(GATE), retry_s=6.0, now=clock, log=lambda line: say("  round: " + line))
    return clock, sysm, say, ducker, rnd


def _sentence(rnd, say, text, started_s_ago):
    r = rnd.utterance(text, t_start=rnd.t_wake - started_s_ago)
    extra = (' -> command: "%s"' % r.rest) if r.rest else ""
    say('second gate on "%s": %s (%s)%s' % (text, r.verdict, r.why, extra))
    return r


def _assistant(rnd, say, sysm, words):
    rnd.speak(lambda: None)
    say('assistant says "%s" (system volume %s)' % (words, sysm.volume))


def duck_story(out):
    out.append("== duck mode: lower the system volume to 25 % while the assistant listens")
    clock, sysm, say, ducker, rnd = _setup("duck", out, volume=50)
    say("music is on, system volume 50")

    out.append("-- 1. a real call over the music")
    say("first gate fired, room is loud -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(1.8)
    if _sentence(rnd, say, "Nova, turn off the desk lamp", started_s_ago=0.3).confirmed:
        _assistant(rnd, say, sysm, "Desk lamp off.")
    clock.advance(1.0)
    say("round over -> %s" % rnd.end())

    out.append("-- 2. a false wake 20 s later is ignored (one round per 60 s)")
    clock.advance(20)
    say("first gate fired -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(1.0)
    _sentence(rnd, say, "and then the chorus comes back in", started_s_ago=0.4)
    say("system volume %s" % sysm.volume)

    out.append("-- 3. the first try is drowned out, the second try works")
    clock.advance(60)
    say("first gate fired -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(1.5)
    _sentence(rnd, say, "uh ... the", started_s_ago=0.2)
    clock.advance(3.0)
    rnd.tick()
    say("first gate fired again -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(1.6)
    if _sentence(rnd, say, "Nova, what time is it?", started_s_ago=0.2).confirmed:
        _assistant(rnd, say, sysm, "It's ten past four.")
    say("round over -> %s" % rnd.end())

    out.append("-- 4. a look-alike on the radio, nobody calls again")
    clock.advance(70)
    say("first gate fired -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(1.2)
    _sentence(rnd, say, "bossa nova for the evening", started_s_ago=0.5)
    for _ in range(7):
        clock.advance(1.0)
        r = rnd.tick()
        if r:
            say("tick -> %s, system volume %s" % (r, sysm.volume))

    out.append("-- 5. the person turns it down by hand while ducked: their choice wins")
    clock.advance(70)
    say("first gate fired -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(0.8)
    sysm.user_sets_volume(5)
    say("person drags the volume to 5")
    if _sentence(rnd, say, "nova, pause for a bit", started_s_ago=0.6).confirmed:
        _assistant(rnd, say, sysm, "Okay.")
    say("round over -> %s" % rnd.end())

    out.append("-- 6. the name in the middle of a sentence is not a call")
    clock.advance(70)
    sysm.user_sets_volume(50)
    say("person turns the music back up to 50")
    say("first gate fired -> %s" % rnd.first_gate(room_loud=True))
    clock.advance(1.0)
    _sentence(rnd, say, "I was telling them about the new nova lamp", started_s_ago=3.2)
    for _ in range(7):
        clock.advance(1.0)
        r = rnd.tick()
        if r:
            say("tick -> %s, system volume %s" % (r, sysm.volume))

    out.append("-- 7. a quiet room: nothing to duck")
    clock.advance(70)
    say("first gate fired, room is quiet -> %s" % rnd.first_gate(room_loud=False))
    clock.advance(1.0)
    if _sentence(rnd, say, "Nova, good night", started_s_ago=0.2).confirmed:
        _assistant(rnd, say, sysm, "Good night.")
    say("round over -> %s" % rnd.end())
    say("counts: %s" % _counts(ducker))


def pause_story(out):
    out.append("== pause mode: pause the music app, resume it when the round is over")
    clock, sysm, say, ducker, rnd = _setup("pause", out, volume=50,
                                           apps={"music-app": "playing", "radio-app": "stopped"},
                                           ignores_pause=("stubborn-app",))
    say("music-app is playing; the room detector does not count music as loud")

    out.append("-- 1. a call: pause, answer at full volume, resume")
    say("first gate fired, room_loud=False -> %s" % rnd.first_gate(room_loud=False))
    clock.advance(1.5)
    if _sentence(rnd, say, "Hey Nova, add oat milk to the list", started_s_ago=0.4).confirmed:
        _assistant(rnd, say, sysm, "Added.")
        say("music-app is %s while the assistant speaks" % sysm.state("music-app"))
    say("round over -> %s" % rnd.end())

    out.append("-- 2. the person presses play themselves during the round: we leave it")
    clock.advance(70)
    say("first gate fired -> %s" % rnd.first_gate())
    clock.advance(1.0)
    sysm.user_sets_state("music-app", "playing")
    say("person presses play")
    _sentence(rnd, say, "never mind", started_s_ago=0.3)
    say("round over -> %s" % rnd.end())

    out.append("-- 3. an app that ignores pause: nothing changed, so the 60 s gap is not used up")
    clock.advance(70)
    sysm.user_sets_state("music-app", "stopped")
    sysm.user_sets_state("stubborn-app", "playing")
    sysm.apps = ("music-app", "radio-app", "stubborn-app")
    say("first gate fired -> %s" % rnd.first_gate())
    rnd.end()
    clock.advance(5)
    sysm.user_sets_state("stubborn-app", "stopped")
    sysm.user_sets_state("music-app", "playing")
    say("5 s later, music-app playing, first gate fired -> %s" % rnd.first_gate())
    say("round over -> %s" % rnd.end())
    say("counts: %s" % _counts(ducker))
    say("actions on the fake system: %s" % ", ".join("%s(%s)" % a for a in sysm.actions))


def _counts(ducker):
    return ", ".join("%s=%d" % (k, v) for k, v in ducker.counts.items())


def run():
    out = []
    duck_story(out)
    out.append("")
    pause_story(out)
    return "\n".join(out) + "\n"
