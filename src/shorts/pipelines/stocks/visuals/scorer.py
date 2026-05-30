"""Relevance scoring — uses OpenAI CLIP via the `open_clip` package.

Loads once per process; scores image-text similarity (0-1 ranged). Higher is
better. Used to rank candidates from multiple retrieval sources for the same
beat.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from ..settings import get_settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model_and_preprocess():
    import open_clip
    import torch

    s = get_settings()
    log.info("Loading CLIP model %s ...", s.clip_model_name)
    model, _, preprocess = open_clip.create_model_and_transforms(
        s.clip_model_name, pretrained="laion2b_s34b_b79k"
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(s.clip_model_name)
    return model, preprocess, tokenizer, torch


def score(image_path: Path, text: str) -> float:
    """Return cosine similarity between image and text in CLIP space."""
    from PIL import Image

    model, preprocess, tokenizer, torch = _model_and_preprocess()
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        log.warning("could not open %s: %s", image_path, e)
        return -1.0

    with torch.no_grad():
        image_features = model.encode_image(preprocess(img).unsqueeze(0))
        text_features = model.encode_text(tokenizer([text]))
        image_features /= image_features.norm(dim=-1, keepdim=True)
        text_features /= text_features.norm(dim=-1, keepdim=True)
        sim = (image_features @ text_features.T).item()
    return float(sim)


def score_batch(image_paths: list[Path], text: str) -> list[float]:
    """Score multiple images against the same text in one pass."""
    from PIL import Image

    model, preprocess, tokenizer, torch = _model_and_preprocess()
    valid: list[tuple[int, Image.Image]] = []
    for i, p in enumerate(image_paths):
        try:
            valid.append((i, Image.open(p).convert("RGB")))
        except Exception:
            continue
    if not valid:
        return [-1.0] * len(image_paths)

    out = [-1.0] * len(image_paths)
    with torch.no_grad():
        imgs = torch.stack([preprocess(im) for _, im in valid])
        image_features = model.encode_image(imgs)
        text_features = model.encode_text(tokenizer([text]))
        image_features /= image_features.norm(dim=-1, keepdim=True)
        text_features /= text_features.norm(dim=-1, keepdim=True)
        sims = (image_features @ text_features.T).squeeze(1).tolist()
    for (idx, _), s in zip(valid, sims, strict=False):
        out[idx] = float(s)
    return out
