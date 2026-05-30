"""Caption chunker — turns word-level timings into phrase-sized caption clips.

Takes a flat list of WordTiming (from ElevenLabs or Whisper) and produces
caption chunks of 4-7 words each, splitting on natural boundaries (punctuation,
long pauses between consecutive words).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..voice.tts import WordTiming

PUNCTUATION_BREAKS = ".!?,:;"
MAX_WORDS_PER_CHUNK = 7
MIN_WORDS_PER_CHUNK = 3
MAX_CHUNK_DURATION_S = 3.5
LONG_PAUSE_MS = 350  # gap between consecutive words that forces a split


@dataclass(frozen=True)
class CaptionChunk:
    text: str
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def chunk_words(words: list[WordTiming]) -> list[CaptionChunk]:
    """Group word timings into caption-sized phrases."""
    if not words:
        return []

    chunks: list[CaptionChunk] = []
    buf: list[WordTiming] = []
    prev_end_ms = words[0].start_ms

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        text = " ".join(_clean(w.word) for w in buf).strip()
        if text:
            chunks.append(CaptionChunk(text=text, start_s=buf[0].start_ms / 1000.0, end_s=buf[-1].end_ms / 1000.0))
        buf = []

    for w in words:
        gap_ms = w.start_ms - prev_end_ms
        too_long = len(buf) >= MAX_WORDS_PER_CHUNK
        too_old = buf and (w.end_ms - buf[0].start_ms) >= MAX_CHUNK_DURATION_S * 1000
        if buf and (too_long or too_old or gap_ms >= LONG_PAUSE_MS):
            flush()
        buf.append(w)
        # Punctuation at end of word forces a split (but keep min length).
        if _ends_with_break(w.word) and len(buf) >= MIN_WORDS_PER_CHUNK:
            flush()
        prev_end_ms = w.end_ms

    flush()
    return chunks


def _clean(word: str) -> str:
    return word.strip()


def _ends_with_break(word: str) -> bool:
    return bool(word) and word.strip().endswith(tuple(PUNCTUATION_BREAKS))
