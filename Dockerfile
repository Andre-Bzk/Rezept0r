# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ARG TARGETARCH

# ffmpeg + ffprobe as static binaries (yt-dlp needs both for audio extraction).
# The Debian package pulls in ~400 MB of X11/desktop dependencies that dpkg then
# unpacks file by file — on an SD card that alone dominates the build time.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /ffprobe /usr/local/bin/

# gosu drops privileges in the entrypoint; the binary avoids an apt transaction
ADD --chmod=755 https://github.com/tianon/gosu/releases/download/1.17/gosu-${TARGETARCH} /usr/local/bin/gosu

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.txt

# Placed after pip: the "latest" URL changes with every yt-dlp release and would
# otherwise invalidate the dependency layer on each build
ADD --chmod=755 https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp /usr/local/bin/yt-dlp

COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY . .

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV TMP_DIR=/app/tmp

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
# Single worker to stay within Pi 3's memory budget
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
