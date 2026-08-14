#!/bin/sh
set -e

APP_UID=${APP_UID:-1000}
APP_GID=${APP_GID:-1000}

# Mounted volumes start out empty on a fresh host, and a mount hides anything the
# image created at these paths — so create the directories here, not at build time
mkdir -p /app/tmp /app/data/images
chown "${APP_UID}:${APP_GID}" /app/tmp /app/data /app/data/images

# Self-update yt-dlp on every container start (Instagram/TikTok break old versions).
# Must not block or fail the boot: network may not be up yet after a Pi reboot.
timeout 60 yt-dlp -U || echo "yt-dlp self-update failed, continuing with installed version"

# Drop from root to app user and run the actual command
exec gosu "${APP_UID}:${APP_GID}" "$@"
