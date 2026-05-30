"""Forced alignment — replace Whisper-transcribed word text with the original
script text, keeping Whisper's word-level timestamps.

Why: Whisper mangles ticker symbols ("KBE" → "KB"), numbers with commas
("3,000" → "3 ,000"), and percentages ("3%" → "3 %"). The original script
text is the ground truth — we just need the timing.

How: a sequence alignment between (script_words) and (whisper_words). For each
script word, find the corresponding whisper word's timestamp range. For
unmatched script words (Whisper missed one), interpolate from neighbors.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from .tts import WordTiming

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\S+")  # any non-whitespace token is a word


def tokenize_script(text: str) -> list[str]:
    """Split script text into display tokens, preserving punctuation."""
    return _WORD_RE.findall(text)


def _norm(s: str) -> str:
    """Normalize a word for matching: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def align_to_timings(script_text: str, whisper_words: list[WordTiming]) -> list[WordTiming]:
    """Return WordTimings whose `word` is the script's original token but whose
    timings come from the best-matching Whisper word.

    If Whisper is missing words, interpolate timestamps linearly. If Whisper has
    extras (transcription added or split a word), they're dropped from the output.
    """
    script_tokens = tokenize_script(script_text)
    if not script_tokens:
        return whisper_words
    if not whisper_words:
        # No Whisper data → fall back to evenly-spaced timing assumption.
        return _evenly_spaced(script_tokens, total_ms=len(script_tokens) * 380)

    script_norm = [_norm(t) for t in script_tokens]
    whisper_norm = [_norm(w.word) for w in whisper_words]

    # Use difflib to find matching runs between the two sequences.
    matcher = SequenceMatcher(a=script_norm, b=whisper_norm, autojunk=False)
    opcodes = matcher.get_opcodes()

    # Build a sparse mapping: script_idx → whisper_idx (when matched).
    mapping: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            # Direct 1:1 mapping
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
        elif tag == "replace":
            # Length-aware fallback: line up positions proportionally.
            n_script = i2 - i1
            n_whisper = j2 - j1
            if n_whisper == 0:
                continue
            for k in range(n_script):
                mapping[i1 + k] = j1 + min(int(k * n_whisper / max(n_script, 1)), n_whisper - 1)
        elif tag == "insert":
            # Whisper has extras → just skip them (don't add to mapping).
            pass
        elif tag == "delete":
            # Script word with no Whisper counterpart → will interpolate.
            pass

    out: list[WordTiming] = []
    for i, tok in enumerate(script_tokens):
        if i in mapping:
            w = whisper_words[mapping[i]]
            out.append(WordTiming(word=tok, start_ms=w.start_ms, end_ms=w.end_ms))
        else:
            # Interpolate: find nearest mapped neighbours.
            prev_w = _nearest_mapped(i, mapping, whisper_words, direction=-1)
            next_w = _nearest_mapped(i, mapping, whisper_words, direction=+1)
            if prev_w and next_w:
                # Linear interpolation between them.
                start = prev_w.end_ms
                end = next_w.start_ms
                if end <= start:
                    end = start + 220
                # Distribute among the unmatched span (this script index relative to span).
                span_total = _count_unmapped_between(i, mapping, len(script_tokens), prev_w, next_w)
                idx_in_span = _position_in_unmapped_span(i, mapping, prev_w)
                if span_total > 0:
                    s = start + int((end - start) * idx_in_span / span_total)
                    e = start + int((end - start) * (idx_in_span + 1) / span_total)
                    out.append(WordTiming(word=tok, start_ms=s, end_ms=max(e, s + 80)))
                    continue
            if prev_w and not next_w:
                t = prev_w.end_ms + 200
                out.append(WordTiming(word=tok, start_ms=t, end_ms=t + 250))
                continue
            if next_w and not prev_w:
                t = max(0, next_w.start_ms - 250)
                out.append(WordTiming(word=tok, start_ms=t, end_ms=next_w.start_ms))
                continue
            # No anchors at all — evenly spaced fallback
            out.append(WordTiming(word=tok, start_ms=i * 380, end_ms=(i + 1) * 380))

    # Pass: ensure monotonically increasing start times.
    last_end = 0
    fixed: list[WordTiming] = []
    for w in out:
        s = max(w.start_ms, last_end)
        e = max(w.end_ms, s + 60)
        fixed.append(WordTiming(word=w.word, start_ms=s, end_ms=e))
        last_end = e
    return fixed


def _nearest_mapped(i: int, mapping: dict[int, int], whisper_words: list[WordTiming],
                    direction: int) -> WordTiming | None:
    j = i + direction
    while 0 <= j < len(whisper_words) + 1:
        if j in mapping:
            return whisper_words[mapping[j]]
        j += direction
    return None


def _count_unmapped_between(i: int, mapping: dict[int, int], n_script: int,
                            prev_w: WordTiming, next_w: WordTiming) -> int:
    # Approximate: count how many consecutive unmapped script tokens are around i.
    k = i
    count = 1
    while k - 1 >= 0 and (k - 1) not in mapping:
        count += 1
        k -= 1
    k = i
    while k + 1 < n_script and (k + 1) not in mapping:
        count += 1
        k += 1
    return count


def _position_in_unmapped_span(i: int, mapping: dict[int, int], prev_w: WordTiming) -> int:
    k = i
    count = 0
    while k - 1 >= 0 and (k - 1) not in mapping:
        count += 1
        k -= 1
    return count


def _evenly_spaced(tokens: list[str], *, total_ms: int) -> list[WordTiming]:
    if not tokens:
        return []
    per = total_ms // max(len(tokens), 1)
    return [
        WordTiming(word=t, start_ms=i * per, end_ms=(i + 1) * per)
        for i, t in enumerate(tokens)
    ]
