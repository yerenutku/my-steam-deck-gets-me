"""Snap misheard names to the names list, after transcription (takes milliseconds).

Rules (conservative, so normal words are never "corrected"):
- A run of 1-3 words whose letters joined equal a listed term is always replaced
  ("dead mines" -> "Deadmines", "storm wind" -> "Stormwind").
- Otherwise a fuzzy match (letters only, edit distance) is allowed only if the words are not all
  plain common English words in lowercase. A capitalised word in the middle of a sentence is one the
  model itself took for a name, so it may be corrected ("Toran" -> "Toren"); "part" never becomes a name.
- Similarity >= 0.75 (1 - edits/longest), terms of 4+ letters; 4-letter terms need the same first letter.
"""

import re
from pathlib import Path

WORD = re.compile(r"[A-Za-z][A-Za-z']*")
HERE = Path(__file__).resolve().parent


def load_common(path=HERE / "common_words.txt"):
    return {l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def letters(s):
    return re.sub(r"[^a-z]", "", s.lower())


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class NameFixer:
    def __init__(self, terms, common=None, plural_ok=()):
        self.common = common if common is not None else load_common()
        self.plural_ok = set(plural_ok)            # terms that may take a plural "s" (items, creatures)
        seen = {}
        for t in terms:
            key = letters(t)
            if len(key) >= 4 and key not in seen:
                seen[key] = t
        self.terms = list(seen.items())            # (letters key, canonical spelling)
        self.exact = dict(self.terms)

    def _protected(self, words, sentence_start, caps_meaningful=True):
        """True if every word is a plain common word the model wrote as a normal word."""
        for k, w in enumerate(words):
            lw = w.lower().replace("'", "")
            capital_mid = caps_meaningful and w[:1].isupper() and not (k == 0 and sentence_start)
            if lw not in self.common or capital_mid:
                return False
        return True

    def _sim(self, key, tkey):
        if abs(len(tkey) - len(key)) > max(2, len(tkey) // 3):
            return 0.0
        if len(tkey) <= 4 and tkey[0] != key[:1]:
            return 0.0
        return 1 - lev(key, tkey) / max(len(key), len(tkey))

    def _best(self, key):
        best, best_sim = None, 0.0
        for tkey, term in self.terms:
            sim = self._sim(key, tkey)
            if sim > best_sim:
                best, best_sim = term, sim
        return (best, best_sim) if best_sim >= 0.75 else (None, best_sim)

    def fix(self, text):
        """Returns (fixed_text, [(heard, replaced_by), ...])."""
        spans = [(m.start(), m.end(), m.group()) for m in WORD.finditer(text)]
        # When the model capitalises nearly every word, capitals say nothing about names.
        caps = sum(w[:1].isupper() for _, _, w in spans)
        caps_meaningful = len(spans) < 3 or caps / len(spans) <= 0.5

        def group_at(i, n):
            if i + n > len(spans):
                return None
            g = spans[i:i + n]
            if any(text[g[k][1]:g[k + 1][0]] != " " for k in range(n - 1)):
                return None
            return g

        out, changes, i, pos = [], [], 0, 0
        while i < len(spans):
            # 1) a listed term that is already there (exact letters) is kept as it is
            exact = None
            for n in (3, 2, 1):
                g = group_at(i, n)
                if g and letters(text[g[0][0]:g[-1][1]]) in self.exact:
                    exact = (n, g, self.exact[letters(text[g[0][0]:g[-1][1]])])
                    break
            if exact:
                n, g, term = exact
                heard = text[g[0][0]:g[-1][1]]
                if heard.replace(" ", "") != term.replace(" ", "") or (" " in heard) != (" " in term):
                    out.append(text[pos:g[0][0]] + term)          # e.g. "dead mines" -> "Deadmines"
                    changes.append((heard, term))
                    pos = g[-1][1]
                i += n
                continue
            # 2) fuzzy: only spans that aren't plain common words, and only if every word helps
            fixed = False
            for n in (3, 2, 1):
                g = group_at(i, n)
                if not g:
                    continue
                words = [w for _, _, w in g]
                before = text[:g[0][0]].rstrip()
                sentence_start = not before or before[-1] in ".!?"
                if self._protected(words, sentence_start, caps_meaningful):
                    continue
                key = letters(text[g[0][0]:g[-1][1]])
                term, sim = self._best(key)
                if not term:
                    continue
                tkey = letters(term)
                if n > 1 and (self._sim(letters(" ".join(words[1:])), tkey) >= sim or
                              self._sim(letters(" ".join(words[:-1])), tkey) >= sim):
                    continue                                       # an edge word doesn't belong to the name
                heard = text[g[0][0]:g[-1][1]]
                if (term in self.plural_ok and heard.lower().endswith("s") and not heard.endswith("'s")
                        and not term.lower().endswith("s") and len(key) > len(tkey)):
                    term += "s"                                    # keep the plural: pillagers -> Pillagers
                out.append(text[pos:g[0][0]] + term)
                changes.append((heard, term))
                pos, i, fixed = g[-1][1], i + n, True
                break
            if not fixed:
                i += 1
        out.append(text[pos:])
        return "".join(out), changes
