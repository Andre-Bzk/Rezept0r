#!/bin/sh
set -e

APP_UID=${APP_UID:-1000}
APP_GID=${APP_GID:-1000}

# Fix ownership of mounted volumes so the app user can write to them
chown "${APP_UID}:${APP_GID}" /app/tmp /app/data /app/data/images

# Drop from root to app user and run the actual command
exec gosu "${APP_UID}:${APP_GID}" "$@"
