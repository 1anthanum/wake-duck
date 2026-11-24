"""The second gate: after the keyword spotter fires, check the transcript before answering.

A keyword spotter (the *first gate*) has to be loose, or it misses you when the
room is noisy. Loose means false wakes. So the first gate only lights a light
and makes room; the assistant answers only when the finished sentence passes
this second gate:

* the name is at the head of the sentence (within ``head_chars`` letters after
  fillers like "um" or "hey") - or, if speech-to-text missed it, an optional
  stricter re-check you supply (for example the same spotter at a higher threshold);
* the name is not part of a look-alike word or phrase ("bossa nova" is not "Nova");
* the first gate fired close to where the sentence started (``lead_s``) - a name
  said in the middle of a sentence is not a call.

Matching is on normalised text (Unicode NFKC, case-folded, letters and digits
only), so it works for any script. Use ``aliases`` for the ways your
speech-to-text tends to misspell the name.
"""
import re
import unicodedata
from dataclasses import dataclass, field


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(ch for ch in text if ch.isalnum())


@dataclass
class GateConfig:
    names: list = field(default_factory=lambda: ["nova"])
    aliases: list = field(default_factory=list)
    lookalikes: list = field(default_factory=list)
    head_chars: int = 8     # the name must start within this many normalised letters
    lead_s: float = 2.0     # first gate fired at most this long after the sentence started


@dataclass
class GateResult:
    verdict: str            # "confirmed" | "rejected" | "mid_sentence"
    why: str                # "name_at_head" | "strict_recheck" | "lookalike" | "no_name" | "late_in_sentence"
    rest: str = ""          # what was said after the name ("turn off the lamp")

    @property
    def confirmed(self):
        return self.verdict == "confirmed"


class SecondGate:
    def __init__(self, config=None):
        self.config = config or GateConfig()
        forms = [normalize(n) for n in list(self.config.names) + list(self.config.aliases)]
        self._forms = sorted({f for f in forms if f}, key=len, reverse=True)
        self._lookalikes = [normalize(x) for x in self.config.lookalikes if normalize(x)]
        if not self._forms:
            raise ValueError("GateConfig.names needs at least one name")

    def _find_head(self, norm):
        """Earliest name form starting within head_chars. Returns (index, form) or None."""
        best = None
        for form in self._forms:
            i = norm.find(form)
            if 0 <= i <= self.config.head_chars and (best is None or i < best[0]):
                best = (i, form)
        return best

    def _is_lookalike(self, norm, i, form):
        for word in self._lookalikes:
            start = norm.find(word)
            while start != -1:
                if start <= i and i + len(form) <= start + len(word):
                    return True
                start = norm.find(word, start + 1)
        return False

    def _rest(self, text, form):
        """Text after the first spoken form of the name, from the original string."""
        pattern = r"[\W_]*".join(re.escape(ch) for ch in form)
        original = unicodedata.normalize("NFKC", text)
        m = re.search(pattern, original, re.IGNORECASE)
        if not m:
            return ""
        return original[m.end():].lstrip(" ,.!?:;-—…").strip()

    def check(self, text, t_start, t_wake, strict=None):
        """text: the transcript of the sentence the first gate fired in.
        t_start: when that sentence started; t_wake: when the first gate fired (same clock).
        strict: optional zero-argument callable, a stricter re-check on the audio."""
        norm = normalize(text)
        head = self._find_head(norm)
        if t_wake - t_start > self.config.lead_s and head is None:
            return GateResult("mid_sentence", "late_in_sentence")
        if head is not None:
            i, form = head
            if self._is_lookalike(norm, i, form):
                return GateResult("rejected", "lookalike")
            return GateResult("confirmed", "name_at_head", self._rest(text, form))
        if strict is not None and strict():
            return GateResult("confirmed", "strict_recheck", "")
        return GateResult("rejected", "no_name")
