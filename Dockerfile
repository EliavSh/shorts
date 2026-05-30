FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/data/hf-cache

WORKDIR /app

# System deps:
#   ffmpeg     — video composition
#   git        — needed by some pip pkgs (whisper)
#   libsndfile1, libsndfile1-dev — librosa/soundfile audio decode
#   curl       — healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      curl \
      libsndfile1 \
      libsndfile1-dev \
      ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/
COPY assets/ assets/

RUN pip install --no-cache-dir -e .

EXPOSE 8000

# Persistent data lives on a Fly volume mounted at /app/data
VOLUME ["/app/data"]

# uvicorn on the unified dashboard. The whole app serves both pipelines.
CMD ["uvicorn", "shorts.core.dashboard.factory:app", "--host", "0.0.0.0", "--port", "8000"]
