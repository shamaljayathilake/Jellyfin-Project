#!/bin/sh

GID="$1"
LOG="/jellyfin-downloader/organizer.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') Download completed: $GID" >> "$LOG"

# Queue the completed GID for the organizer
echo "$GID" >> /jellyfin-downloader/queue/completed
