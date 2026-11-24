"""Tests run on fakes only: fake clock, fake volume, fake apps, fake command runner. Nothing makes a sound."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from wake_duck import DuckConfig, Ducker, GateConfig, SecondGate, WakeRound, normalize  # noqa: E402
from wake_duck.__main__ import main  # noqa: E402
from wake_duck.backends import FakeClock, FakeSystem  # noqa: E402
from wake_duck.macos import MacMusicApps, MacVolume  # noqa: E402
from wake_duck import demo  # noqa: E402


def make(mode="duck", volume=50, apps=None, ignores=(), memo=None, **cfg):
    clock = FakeClock()
    sysm = FakeSystem(volume=volume, apps=apps, ignores_pause=ignores)
    d = Ducker(volume=sysm, player=sysm, config=DuckConfig(mode=mode, **cfg), now=clock, wall=clock,
               sleep=clock.sleep, memo_path=memo)
    return clock, sysm, d


class TestDuckMode(unittest.TestCase):
    def test_ducks_to_percent_and_restores(self):
        _, s, d = make()
        self.assertEqual(d.on_wake(room_loud=True), "ducked")
        self.assertEqual(s.volume, 13)
        self.assertEqual(d.restore(), "restored")
        self.assertEqual(s.volume, 50)

    def test_never_below_one_and_already_low(self):
        _, s, d = make(volume=2)
        self.assertEqual(d.on_wake(True), "ducked")
        self.assertEqual(s.volume, 1)
        _, s, d = make(volume=1)
        self.assertEqual(d.on_wake(True), "already_low")
        self.assertEqual(s.actions, [])

    def test_quiet_room_does_nothing(self):
        _, s, d = make()
        self.assertEqual(d.on_wake(room_loud=False), "quiet")
        self.assertEqual(s.actions, [])

    def test_muted_zero_or_unreadable_does_nothing(self):
        for setup in ("muted", "zero", "unreadable"):
            _, s, d = make(volume=0 if setup == "zero" else 50)
            s.muted = setup == "muted"
            s.readable = setup != "unreadable"
            self.assertEqual(d.on_wake(True), "nothing_playing", setup)
            self.assertEqual(s.actions, [], setup)

    def test_hand_change_wins_but_small_drift_is_ignored(self):
        _, s, d = make()
        d.on_wake(True)
        s.user_sets_volume(30)
        self.assertEqual(d.restore(), "user_changed")
        self.assertEqual(s.volume, 30)
        clock, s, d = make()
        d.on_wake(True)
        s.user_sets_volume(15)          # 13 -> 15: within drift 2, device step
        self.assertEqual(d.restore(), "restored")
        self.assertEqual(s.volume, 50)

    def test_one_round_per_gap(self):
        clock, s, d = make()
        d.on_wake(True)
        d.restore()
        clock.advance(59)
        self.assertEqual(d.on_wake(True), "too_soon")
        clock.advance(1)
        self.assertEqual(d.on_wake(True), "ducked")

    def test_second_wake_while_holding_keeps_original(self):
        _, s, d = make()
        d.on_wake(True)
        self.assertEqual(d.on_wake(True), "already_holding")
        d.restore()
        self.assertEqual(s.volume, 50)

    def test_tick_restores_on_idle_and_on_limit(self):
        clock, s, d = make()
        d.on_wake(True)
        self.assertIsNone(d.tick())
        self.assertEqual(d.tick(idle=True), "restored")
        clock.advance(60)
        d.on_wake(True)
        clock.advance(7.9)
        self.assertIsNone(d.tick())
        clock.advance(0.1)
        self.assertEqual(d.tick(), "restored")

    def test_restores_before_the_assistant_speaks(self):
        _, s, d = make()
        heard = []
        speak = d.wrap_speaker(lambda words: heard.append((words, s.volume)))
        d.on_wake(True)
        speak("hello")
        self.assertEqual(heard, [("hello", 50)])
        self.assertTrue(callable(speak.__wrapped__))

    def test_close_restores(self):
        _, s, d = make()
        d.on_wake(True)
        self.assertEqual(d.close(), "restored")
        self.assertEqual(s.volume, 50)
        self.assertIsNone(d.close())

    def test_broken_backend_never_raises(self):
        _, s, d = make()
        s.get_volume = mock.Mock(side_effect=OSError("gone"))
        self.assertEqual(d.on_wake(True), "error")
        self.assertFalse(d.holding)

    def test_config(self):
        self.assertEqual(DuckConfig(duck_percent=1).duck_percent, 5.0)
        self.assertEqual(DuckConfig(duck_percent=99).duck_percent, 80.0)
        with self.assertRaises(ValueError):
            DuckConfig(mode="loud")

    def test_off_mode(self):
        _, s, d = make(mode="off")
        self.assertEqual(d.on_wake(True), "off")
        self.assertEqual(s.actions, [])


class TestCrashMemo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.memo = os.path.join(self.dir.name, "memo.json")

    def tearDown(self):
        self.dir.cleanup()

    def _crash(self):
        clock, s, d = make(memo=self.memo)
        clock.advance(1000)
        d.on_wake(True)                 # ducked to 13, then the process "dies"
        return clock, s

    def test_restores_recent_untouched(self):
        clock, s = self._crash()
        clock.advance(30)
        d2 = Ducker(volume=s, player=s, now=clock, wall=clock, memo_path=self.memo)
        self.assertEqual(d2.recover_on_start(), "restored")
        self.assertEqual(s.volume, 50)
        with open(self.memo, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {})
        self.assertIsNone(d2.recover_on_start())

    def test_too_old_or_touched_is_left(self):
        clock, s = self._crash()
        clock.advance(601)
        d2 = Ducker(volume=s, player=s, now=clock, wall=clock, memo_path=self.memo)
        self.assertEqual(d2.recover_on_start(), "too_old")
        self.assertEqual(s.volume, 13)
        clock, s = self._crash()
        s.user_sets_volume(40)
        d3 = Ducker(volume=s, player=s, now=clock, wall=clock, memo_path=self.memo)
        self.assertEqual(d3.recover_on_start(), "user_changed")
        self.assertEqual(s.volume, 40)

    def test_normal_restore_clears_memo(self):
        clock, s, d = make(memo=self.memo)
        d.on_wake(True)
        d.restore()
        with open(self.memo, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {})


class TestPauseMode(unittest.TestCase):
    def test_pauses_playing_apps_without_room_loud_and_resumes(self):
        _, s, d = make(mode="pause", apps={"a": "playing", "b": "stopped"})
        self.assertEqual(d.on_wake(room_loud=False), "paused")
        self.assertEqual((s.state("a"), s.state("b")), ("paused", "stopped"))
        d.before_speaking()
        self.assertEqual(s.state("a"), "paused")          # stays paused while the assistant talks
        self.assertEqual(d.restore(), "resumed")
        self.assertEqual(s.actions, [("pause", "a"), ("play", "a")])

    def test_resumes_only_what_is_still_paused(self):
        _, s, d = make(mode="pause", apps={"a": "playing"})
        d.on_wake()
        s.user_sets_state("a", "stopped")
        s.user_sets_state("a", "playing")
        self.assertEqual(d.restore(), "left_alone")
        self.assertEqual(s.actions, [("pause", "a")])

    def test_ignored_pause_does_not_use_up_the_gap(self):
        clock, s, d = make(mode="pause", apps={"a": "playing"}, ignores=("a",))
        self.assertEqual(d.on_wake(), "did_not_stop")
        self.assertFalse(d.holding)
        s.ignores_pause.clear()
        clock.advance(5)
        self.assertEqual(d.on_wake(), "paused")

    def test_nothing_playing(self):
        _, s, d = make(mode="pause", apps={"a": "paused"})
        self.assertEqual(d.on_wake(), "nothing_playing")
        self.assertEqual(s.actions, [])

    def test_pause_limit(self):
        clock, s, d = make(mode="pause", apps={"a": "playing"})
        d.on_wake()
        clock.advance(599)
        self.assertIsNone(d.tick())
        clock.advance(1)
        self.assertEqual(d.tick(), "resumed")


GATE = GateConfig(names=["nova"], aliases=["noba"], lookalikes=["bossa nova", "casanova", "supernova"])


class TestSecondGate(unittest.TestCase):
    def setUp(self):
        self.g = SecondGate(GATE)

    def test_name_at_head_with_fillers(self):
        for text in ("Nova, lights off", "um, hey Nova - lights off", "NOVA... lights off", "noba lights off"):
            r = self.g.check(text, t_start=0.0, t_wake=0.5)
            self.assertEqual((r.verdict, r.rest), ("confirmed", "lights off"), text)

    def test_lookalike_rejected_only_where_it_covers_the_name(self):
        self.assertEqual(self.g.check("bossa nova tonight", 0, 0.5).why, "lookalike")
        self.assertEqual(self.g.check("Casanova was here", 0, 0.5).why, "lookalike")
        r = self.g.check("Nova, play some bossa nova", 0, 0.5)
        self.assertEqual((r.verdict, r.rest), ("confirmed", "play some bossa nova"))

    def test_mid_sentence(self):
        self.assertEqual(self.g.check("so I told them about nova", 0, 3.0).verdict, "mid_sentence")
        self.assertEqual(self.g.check("so I told them about nova", 0, 1.0).verdict, "rejected")
        self.assertEqual(self.g.check("Nova, are you there", 0, 3.0).verdict, "confirmed")  # spotter was late

    def test_strict_recheck_fallback(self):
        r = self.g.check("lights off", 0, 0.5, strict=lambda: True)
        self.assertEqual((r.verdict, r.why), ("confirmed", "strict_recheck"))
        self.assertEqual(self.g.check("lights off", 0, 0.5, strict=lambda: False).verdict, "rejected")

    def test_normalisation_and_other_scripts(self):
        self.assertEqual(normalize("ＮＯＶＡ, hi!"), "novahi")   # full-width letters
        greek = SecondGate(GateConfig(names=["Νόβα"]))
        r = greek.check("νόβα, καλημέρα", 0, 0.5)
        self.assertEqual(r.verdict, "confirmed")

    def test_needs_a_name(self):
        with self.assertRaises(ValueError):
            SecondGate(GateConfig(names=["!!"]))


def make_round(mode="duck", retry_s=6.0, **kw):
    clock, s, d = make(mode=mode, **kw)
    return clock, s, d, WakeRound(d, SecondGate(GATE), retry_s=retry_s, now=clock)


class TestWakeRound(unittest.TestCase):
    def test_retry_inside_window_is_the_same_round(self):
        clock, s, d, r = make_round()
        self.assertEqual(r.first_gate(room_loud=True), "ducked")
        clock.advance(1)
        self.assertEqual(r.utterance("uh the", clock() - 0.3).verdict, "rejected")
        self.assertEqual(r.state, "retry")
        clock.advance(3)
        self.assertIsNone(r.tick())
        self.assertEqual(s.volume, 13)
        self.assertEqual(r.first_gate(room_loud=True), "retry")
        clock.advance(1)
        self.assertTrue(r.utterance("Nova, what time is it", clock() - 0.8).confirmed)
        self.assertEqual(d.counts["held"], 1)
        self.assertEqual(s.actions, [("set_volume", 13)])

    def test_no_retry_restores_after_window(self):
        clock, s, d, r = make_round()
        r.first_gate(True)
        clock.advance(1)
        r.utterance("bossa nova", clock() - 0.5)
        clock.advance(5.9)
        self.assertIsNone(r.tick())
        clock.advance(0.1)
        self.assertEqual(r.tick(), "restored")
        self.assertEqual((r.state, s.volume), ("idle", 50))

    def test_zero_window_restores_at_once(self):
        clock, s, d, r = make_round(retry_s=0)
        r.first_gate(True)
        r.utterance("nothing", clock())
        self.assertEqual((r.state, s.volume), ("idle", 50))

    def test_utterance_without_wake(self):
        _, _, _, r = make_round()
        self.assertEqual(r.utterance("Nova, hi", 0).why, "not_armed")

    def test_pause_round_resumes_at_end(self):
        clock, s, d, r = make_round(mode="pause", apps={"a": "playing"})
        r.first_gate()
        clock.advance(1)
        self.assertTrue(r.utterance("hey nova, next song", clock() - 0.5).confirmed)
        r.speak(lambda: None)
        self.assertEqual(s.state("a"), "paused")
        self.assertEqual(r.end(), "resumed")
        self.assertEqual(s.state("a"), "playing")


class TestMacBackends(unittest.TestCase):
    """A fake `run` stands in for osascript. subprocess is patched to fail loudly if anything reaches it."""

    def setUp(self):
        p = mock.patch.object(subprocess, "run", side_effect=AssertionError("tests must not run commands"))
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def runner(self, reply):
        def run(args):
            self.calls.append(args)
            return reply
        return run

    def test_volume(self):
        v = MacVolume(run=self.runner("output volume:42, input volume:50, alert volume:100, output muted:false"))
        self.assertEqual(v.get_volume(), (42, False))
        v.set_volume(130)
        self.assertEqual(self.calls[-1], ["osascript", "-e", "set volume output volume 100"])
        v = MacVolume(run=self.runner("output volume:missing value, input volume:50, alert volume:100, output muted:true"))
        self.assertEqual(v.get_volume(), (None, True))

    def test_music_apps_never_launch_an_app(self):
        m = MacMusicApps(run=self.runner("playing"))
        self.assertEqual(m.state("com.apple.Music"), "playing")
        m.pause("com.spotify.client")
        for args in self.calls:
            self.assertIn('is running then tell application id', args[2])
        self.assertIsNone(MacMusicApps(run=self.runner("")).state("com.apple.Music"))
        with self.assertRaises(ValueError):
            m.play('x" to quit --')


class TestDemoAndCli(unittest.TestCase):
    def test_demo_output_is_current(self):
        """examples/demo-output.txt is exactly what `python -m wake_duck demo` prints."""
        with open(os.path.join(ROOT, "examples", "demo-output.txt"), encoding="utf-8") as f:
            self.assertEqual(demo.run(), f.read())

    def test_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(["demo"]), 0)
        self.assertIn("== pause mode", buf.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
            main(["--version"])
        self.assertEqual(e.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
