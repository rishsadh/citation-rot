"""64-bit simhash of page text, so small edits do not count as a changed page."""
import hashlib
import re

_WORD = re.compile(r"\w+", re.UNICODE)


def simhash(text, shingle=3, max_words=20000):
    words = _WORD.findall(text.lower())[:max_words]
    if not words:
        return 0
    grams = [" ".join(words[i:i + shingle]) for i in range(max(1, len(words) - shingle + 1))]
    v = [0] * 64
    for g in grams:
        h = int.from_bytes(hashlib.md5(g.encode("utf-8")).digest()[:8], "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(64) if v[i] > 0)


def distance(a, b):
    return bin(a ^ b).count("1")
