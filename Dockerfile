# BullpenLM trainer — single-container image you host on your Mac Mini / VPS.
# Teammates Tailscale (or reverse-proxy) into your host and connect to :7878.
#
# Build:   docker build -t bullpenlm .
# Run:     docker run -d -p 7878:7878 \
#            -v $(pwd)/organizations:/app/organizations \
#            -v $(pwd)/training-runs:/app/training-runs \
#            -v $(pwd)/team:/app/team \
#            -v $(pwd)/personas:/app/personas \
#            --name bullpenlm bullpenlm
#
# The four mounted volumes are the team's shared state. Everything else
# (binaries, code) lives inside the container. To upgrade the server,
# rebuild the image and re-run; the volumes persist your team's data.

FROM python:3.11-slim

# whisper.cpp build deps + ffmpeg for audio conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ffmpeg \
        curl \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# Build whisper.cpp from source (CPU only — works on Mac, x86, ARM).
# For Mac M-series hosts that pass an Apple GPU through to Docker, the
# Metal build is faster but not portable; CPU build is reliable everywhere.
RUN git clone --depth=1 https://github.com/ggerganov/whisper.cpp /opt/whisper.cpp \
    && cd /opt/whisper.cpp \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --config Release -j \
    && cp build/bin/whisper-cli /usr/local/bin/whisper-cli

# Pre-download the small.en whisper model (~466MB). If you'd rather
# bind-mount your own model dir, comment out and add a -v flag at runtime.
RUN mkdir -p /opt/whisper-models && \
    curl -L -o /opt/whisper-models/ggml-small.en.bin \
        https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin

WORKDIR /app
COPY requirements.txt* /app/
RUN pip install --no-cache-dir pypdf certifi

# Application code
COPY adapters/   /app/adapters/
COPY server/     /app/server/
COPY personas/   /app/personas/
COPY floor/      /app/floor/
COPY scripts/    /app/scripts/

# Symlink the whisper model into the server's expected path
RUN mkdir -p /app/server/models && \
    ln -s /opt/whisper-models/ggml-small.en.bin /app/server/models/ggml-small.en.bin

EXPOSE 7878
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -sf http://localhost:7878/api/team/roster > /dev/null || exit 1

CMD ["python3", "server/server.py"]
