#!/bin/sh

GID="$1"

echo "$GID" >> /jellyfin-downloader/queue/completed
