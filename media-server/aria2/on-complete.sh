#!/bin/sh

GID="$1"

echo "$(date '+%Y-%m-%d %H:%M:%S') aria2 completed GID=$GID" >> /config/organizer.log
