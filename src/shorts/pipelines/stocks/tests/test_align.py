"""Tests for the forced-alignment module — the R1 fix."""
from shorts.pipelines.stocks.voice.align import align_to_timings, tokenize_script
from shorts.pipelines.stocks.voice.tts import WordTiming


def test_replaces_mistranscribed_ticker() -> None:
    """Whisper transcribed 'KB' but the script said 'KBE'. Output keeps 'KBE'."""
    script = "KBE is the bank ETF"
    whisper = [
        WordTiming("KB", 0, 200),
        WordTiming("is", 220, 320),
        WordTiming("the", 340, 460),
        WordTiming("bank", 480, 660),
        WordTiming("ETF", 700, 920),
    ]
    out = align_to_timings(script, whisper)
    assert [w.word for w in out] == ["KBE", "is", "the", "bank", "ETF"]
    # The KBE word inherits the KB timing
    assert out[0].start_ms == 0


def test_merges_split_percent_token() -> None:
    """Whisper split '3%' into two tokens; script has '3%' as one. Output collapses."""
    script = "up 3% today"
    whisper = [
        WordTiming("up", 0, 200),
        WordTiming("3", 220, 320),
        WordTiming("%", 330, 380),
        WordTiming("today", 400, 720),
    ]
    out = align_to_timings(script, whisper)
    assert [w.word for w in out] == ["up", "3%", "today"]


def test_merges_split_thousands_comma() -> None:
    """Whisper split '3,000' into ['3', ',000']; script has '3,000'."""
    script = "cuts 3,000 jobs"
    whisper = [
        WordTiming("cuts", 0, 240),
        WordTiming("3", 260, 360),
        WordTiming(",000", 370, 540),
        WordTiming("jobs", 560, 760),
    ]
    out = align_to_timings(script, whisper)
    assert [w.word for w in out] == ["cuts", "3,000", "jobs"]


def test_interpolates_missing_whisper_word() -> None:
    """Whisper dropped a word; aligner interpolates timing from neighbors."""
    script = "the Fed will hold rates"
    whisper = [
        WordTiming("the", 0, 200),
        WordTiming("Fed", 220, 380),
        # 'will' missing
        WordTiming("hold", 600, 800),
        WordTiming("rates", 820, 1100),
    ]
    out = align_to_timings(script, whisper)
    assert [w.word for w in out] == ["the", "Fed", "will", "hold", "rates"]
    # 'will' should be between Fed and hold
    will = next(w for w in out if w.word == "will")
    assert 380 <= will.start_ms <= 600


def test_tokenize_preserves_punctuation() -> None:
    assert tokenize_script("Nvidia is up 1.2%. Wow.") == ["Nvidia", "is", "up", "1.2%.", "Wow."]


def test_empty_inputs() -> None:
    assert align_to_timings("", []) == []
    assert align_to_timings("hello world", []) != []  # falls back to evenly-spaced
