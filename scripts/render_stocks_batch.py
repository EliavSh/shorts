"""One-off batch renderer for the curated stocks fixture set.

Renders each fixture end-to-end (TTS -> visual director -> compose) straight into
the review store's v1/short.mp4 so the dashboard lists it. Per-clip try/except so
one failure never aborts the batch. NO external timeout — a killed encode is what
corrupted earlier renders, so each clip runs to completion.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

from shorts.pipelines.stocks.compose import compose_video
from shorts.pipelines.stocks.pipeline import emit_review_state
from shorts.pipelines.stocks.script.writer import write_script_from_fixture
from shorts.pipelines.stocks.settings import get_settings
from shorts.pipelines.stocks.voice.tts import synthesize

NAMES = [
    "nvda_earnings",
    "tsmc_pivot",
    "apple_services",
    "palantir_run",
    "lly_novo_glp1",
    "costco_membership",
    "asml_monopoly",
    "broadcom_ai",
    "netflix_password",
    "fed_june",
    "tesla_energy",
]
LANG = "en"
FIX_DIR = Path(__file__).resolve().parent.parent / "src/shorts/pipelines/stocks/tests/fixtures"


def render_one(name: str) -> tuple[bool, str]:
    s = get_settings()
    fixture = FIX_DIR / f"script_{name}_{LANG}.json"
    if not fixture.exists():
        return False, f"fixture missing: {fixture}"
    script = write_script_from_fixture(fixture)
    slug = f"{name}_{LANG}"
    work_dir = s.output_dir / slug
    out_mp4 = emit_review_state(slug=slug, script=script, creator_handle=name)
    text = script.narration_text()
    tts = synthesize(text=text, lang=LANG, out_dir=work_dir)
    compose_video(script=script, tts=tts, out_path=out_mp4)
    return True, f"{out_mp4}  audio={tts.duration_s:.1f}s"


def main() -> int:
    global NAMES
    if len(sys.argv) > 1:
        NAMES = sys.argv[1:]
    print(f"=== Rendering {len(NAMES)} stocks clips ===", flush=True)
    results = []
    for i, name in enumerate(NAMES, 1):
        t0 = time.time()
        print(f"\n[{i}/{len(NAMES)}] {name} ...", flush=True)
        try:
            ok, msg = render_one(name)
            dt = time.time() - t0
            status = "OK" if ok else "FAIL"
            print(f"[{i}/{len(NAMES)}] {name}: {status} ({dt:.0f}s) {msg}", flush=True)
            results.append((name, ok, msg, dt))
        except Exception as e:
            dt = time.time() - t0
            print(f"[{i}/{len(NAMES)}] {name}: EXCEPTION ({dt:.0f}s) {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            results.append((name, False, f"{type(e).__name__}: {e}", dt))

    print("\n=== SUMMARY ===", flush=True)
    n_ok = sum(1 for _, ok, _, _ in results if ok)
    for name, ok, msg, dt in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {name:20s} {dt:5.0f}s  {msg}", flush=True)
    print(f"=== {n_ok}/{len(NAMES)} succeeded ===", flush=True)
    return 0 if n_ok == len(NAMES) else 1


if __name__ == "__main__":
    sys.exit(main())
