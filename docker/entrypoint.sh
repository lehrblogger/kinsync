#!/bin/bash
set -e

mkdir -p /data/collections/collection-root

# Initialize shared calendar service account htpasswd (always runs to pick up password changes)
if [ -n "$RADICALE_SYNC_USER" ] && [ -n "$RADICALE_SYNC_PASSWORD" ]; then
    htpasswd -bB /data/users "$RADICALE_SYNC_USER" "$RADICALE_SYNC_PASSWORD"
fi

# Initialize family member htpasswd on first run if credentials are provided
if [ -n "$RADICALE_USER" ] && [ -n "$RADICALE_PASSWORD" ]; then
    if ! grep -q "^$RADICALE_USER:" /data/users 2>/dev/null; then
        htpasswd -bB /data/users "$RADICALE_USER" "$RADICALE_PASSWORD"
    fi
fi

# Create shared calendar collection on first run
if [ -n "$RADICALE_SYNC_USER" ] && [ -n "$RADICALE_CALENDAR" ]; then
    CALENDAR_DIR="/data/collections/collection-root/$RADICALE_SYNC_USER/$RADICALE_CALENDAR"
    mkdir -p "$CALENDAR_DIR"
    if [ ! -f "$CALENDAR_DIR/.Radicale.props" ]; then
        echo '{"D:displayname": "Four Seasons", "C:supported-calendar-component-set": "VEVENT", "tag": "VCALENDAR"}' \
            > "$CALENDAR_DIR/.Radicale.props"
    fi
fi

# Migrate old calendar data from user namespace to shared namespace
if [ -n "$RADICALE_USER" ] && [ -n "$RADICALE_SYNC_USER" ] && [ -n "$RADICALE_CALENDAR" ]; then
    OLD_DIR="/data/collections/collection-root/$RADICALE_USER/$RADICALE_CALENDAR"
    NEW_DIR="/data/collections/collection-root/$RADICALE_SYNC_USER/$RADICALE_CALENDAR"
    if [ -d "$OLD_DIR" ] && [ ! "$(ls -A "$NEW_DIR" 2>/dev/null)" ]; then
        cp -rn "$OLD_DIR/." "$NEW_DIR/"
        echo "Migrated calendar data from $OLD_DIR to $NEW_DIR"
    fi
fi

# Create default rights file on first run
if [ ! -f /data/rights ] && [ -n "$RADICALE_SYNC_USER" ]; then
    cat > /data/rights << EOF
# $RADICALE_SYNC_USER service account: full write access to its calendars.
[$RADICALE_SYNC_USER-owner]
user: $RADICALE_SYNC_USER
collection: $RADICALE_SYNC_USER(/.*)?
permissions: RrWw

# All authenticated users: read-only access to $RADICALE_SYNC_USER calendars.
[family-read-$RADICALE_SYNC_USER]
user: .+
collection: $RADICALE_SYNC_USER(/.*)?
permissions: Rr

# Each user: full access to their own personal collections.
[owner]
user: .+
collection: {user}(/.*)?
permissions: RrWw
EOF
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
