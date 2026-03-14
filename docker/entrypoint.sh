#!/bin/bash
set -e

mkdir -p /data/collections/collection-root

# Initialize htpasswd on first run if credentials are provided
if [ ! -f /data/users ] && [ -n "$RADICALE_USER" ] && [ -n "$RADICALE_PASSWORD" ]; then
    htpasswd -cbB /data/users "$RADICALE_USER" "$RADICALE_PASSWORD"
fi

# Create calendar collection on first run
if [ -n "$RADICALE_USER" ] && [ -n "$RADICALE_CALENDAR" ]; then
    CALENDAR_DIR="/data/collections/collection-root/$RADICALE_USER/$RADICALE_CALENDAR"
    mkdir -p "$CALENDAR_DIR"
    if [ ! -f "$CALENDAR_DIR/.Radicale.props" ]; then
        echo '{"D:displayname": "Four Seasons", "C:supported-calendar-component-set": "VEVENT", "tag": "VCALENDAR"}' \
            > "$CALENDAR_DIR/.Radicale.props"
    fi
fi

# Initialize git archive repo on first run
if [ -n "$GIT_REMOTE_URL" ]; then
    REPO="/data/collections/collection-root"
    if [ ! -d "$REPO/.git" ]; then
        git -C "$REPO" init
        git -C "$REPO" config user.email "kinsync@fly.io"
        git -C "$REPO" config user.name "kinsync"
        git -C "$REPO" remote add origin "$GIT_REMOTE_URL"
    else
        git -C "$REPO" remote set-url origin "$GIT_REMOTE_URL"
    fi
fi

# Make CRON_SECRET available to cron jobs
echo "CRON_SECRET=$CRON_SECRET" >> /etc/environment

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
