"""TTS — text to audio + word-level timings.

Two providers:
- `edge` (default, free): Microsoft Edge TTS endpoints via the `edge-tts`
  package. Returns word-boundary events; we map them to WordTiming.
- `elevenlabs` (production): Multilingual v2 with cloned voice. Requires
  ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID_EN.

The provider is selected by `settings.tts_provider`. Both return the same
`TTSResult` shape so the composer is provider-agnostic.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from ..settings import get_settings
from shorts.core.usage import record as record_usage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    duration_ms: int
    words: list[WordTiming]

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0


def synthesize(*, text: str, lang: str, out_dir: Path) -> TTSResult:
    """Generate speech + word timings. Provider dispatched via settings."""
    s = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    if s.tts_provider == "elevenlabs":
        return _synthesize_elevenlabs(text=text, lang=lang, out_dir=out_dir)
    if s.tts_provider == "edge":
        return _synthesize_edge(text=text, lang=lang, out_dir=out_dir)
    raise ValueError(f"Unknown tts_provider: {s.tts_provider!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Provider: edge-tts (free)
# ─────────────────────────────────────────────────────────────────────────────

def _synthesize_edge(*, text: str, lang: str, out_dir: Path) -> TTSResult:
    """Synthesize via edge-tts, then Whisper-align the audio for word timings.

    edge-tts emits only SentenceBoundary events as of 2024 (word boundaries were
    removed from the Edge endpoints), so we get word-level alignment from
    Whisper running on the synthesized audio.
    """
    import edge_tts

    s = get_settings()
    voice = s.edge_voice_en  # English-only v1
    log.info("edge-tts synth: voice=%s chars=%d", voice, len(text))
    out_path = out_dir / "voice.mp3"

    async def run_synth() -> None:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate="+0%", pitch="+0Hz")
        with out_path.open("wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])

    asyncio.run(run_synth())
    record_usage("edge_tts", "tts", units=len(text), note=f"voice={voice}")

    words = _align_words_with_whisper(audio_path=out_path, lang=lang)
    duration_ms = words[-1].end_ms if words else 0
    return TTSResult(audio_path=out_path, duration_ms=duration_ms, words=words)


_FW_MODEL = None


def _get_fw_model():
    """Lazily load (and cache) the faster-whisper model.

    int8 on CPU keeps the 'small' weights at ~250MB RAM (vs ~1GB+ for
    openai-whisper fp32), so a 2GB cloud render machine doesn't OOM, and it's
    noticeably faster on CPU. Weights cache under HF_HOME (a Fly volume in
    production) so they download only once.
    """
    global _FW_MODEL
    if _FW_MODEL is None:
        from faster_whisper import WhisperModel
        _FW_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
    return _FW_MODEL


def _align_words_with_whisper(*, audio_path: Path, lang: str) -> list[WordTiming]:
    """Run Whisper on a synthesized audio file and return word-level timings.

    Uses faster-whisper (CTranslate2) for a small RAM footprint. Whisper wants
    16kHz mono; on Windows ffmpeg isn't on PATH, so we decode to a float32 array
    ourselves with the imageio-ffmpeg bundled binary and hand that to Whisper.
    """
    import subprocess
    import wave

    import imageio_ffmpeg
    import numpy as np

    log.info("Whisper-aligning %s (lang=%s)", audio_path.name, lang)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    wav_path = audio_path.with_suffix(".whisper.wav")
    cmd = [ffmpeg, "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    with wave.open(str(wav_path), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

    model = _get_fw_model()
    segments, _info = model.transcribe(pcm, language=lang, word_timestamps=True)

    words: list[WordTiming] = []
    for seg in segments:
        for w in (seg.words or []):
            text = (w.word or "").strip()
            if not text:
                continue
            start_ms = int(float(w.start) * 1000)
            end_ms = int(float(w.end) * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 60
            words.append(WordTiming(word=text, start_ms=start_ms, end_ms=end_ms))
    return words


# ─────────────────────────────────────────────────────────────────────────────
# Provider: ElevenLabs Multilingual v2 (production)
# ─────────────────────────────────────────────────────────────────────────────

def _synthesize_elevenlabs(*, text: str, lang: str, out_dir: Path) -> TTSResult:
    from elevenlabs.client import ElevenLabs

    s = get_settings()
    if not s.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set — cannot call ElevenLabs.")
    voice_id = s.elevenlabs_voice_id_en
    if not voice_id:
        raise RuntimeError("ELEVENLABS_VOICE_ID_EN not set.")

    client = ElevenLabs(api_key=s.elevenlabs_api_key)
    log.info("ElevenLabs synth: voice=%s chars=%d", voice_id, len(text))

    response = client.text_to_speech.with_timestamps(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    audio_path = out_dir / "voice.mp3"
    audio_path.write_bytes(base64.b64decode(response.audio_base_64))
    record_usage("elevenlabs", "tts", units=len(text), note=f"voice={voice_id}")

    alignment = response.alignment
    chars = list(alignment.characters)
    starts_ms = [int(x * 1000) for x in alignment.character_start_times_seconds]
    ends_ms = [int(x * 1000) for x in alignment.character_end_times_seconds]

    words = _chars_to_words(chars, starts_ms, ends_ms)
    duration_ms = ends_ms[-1] if ends_ms else 0
    return TTSResult(audio_path=audio_path, duration_ms=duration_ms, words=words)


def _chars_to_words(chars: list[str], starts: list[int], ends: list[int]) -> list[WordTiming]:
    words: list[WordTiming] = []
    buf: list[str] = []
    buf_start: int | None = None
    buf_end: int = 0
    for ch, s, e in zip(chars, starts, ends, strict=False):
        if ch.isspace():
            if buf:
                words.append(WordTiming(word="".join(buf), start_ms=buf_start or 0, end_ms=buf_end))
                buf, buf_start = [], None
        else:
            if buf_start is None:
                buf_start = s
            buf.append(ch)
            buf_end = e
    if buf:
        words.append(WordTiming(word="".join(buf), start_ms=buf_start or 0, end_ms=buf_end))
    return words
