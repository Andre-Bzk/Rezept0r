FROM python:3.12-slim-bookworm

# Install system dependencies (ffmpeg required by yt-dlp for audio extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp (standalone binary, always up-to-date)
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && \
    chmod +x /usr/local/bin/yt-dlp

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/tmp /app/data

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV TMP_DIR=/app/tmp

EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
# Single worker to stay within Pi 3's memory budget
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
