# Jellyfin Media Stack

This project provides a self-hosted Jellyfin media stack built with Docker Compose.

It combines:

- Jellyfin for streaming your library
- aria2 for torrent downloads
- a small web UI for managing downloads and uploads
- automatic sorting of completed media into the right Jellyfin folders
- manual uploads for movies and general videos
- direct deletion of unwanted or pending torrent downloads

It is designed for a home-lab setup where you want one simple workflow for both downloaded and manually added media.

## Features

- Add torrent magnet links from the web UI
- Watch active, waiting, and completed downloads
- Delete unwanted or pending torrents from the UI
- Automatically organize completed downloads into Movies, TV, or Videos
- Manually upload a movie or video without using torrents
- Use a separate Jellyfin `Videos` library for non-movie, non-TV content
- Reuse your existing Jellyfin config and cache data
- Refresh the Jellyfin library after files are moved or uploaded

## Project Layout

```text
.
├── compose.yml
├── .env.example
└── media-server
    ├── aria2
    ├── aria2-image
    ├── jellyfin
    └── jellyfin-downloader-ui
```

## Folder Expectations

The stack expects these host folders:

- `/mnt/media/downloads`
- `/mnt/media/movies`
- `/mnt/media/tv`
- `/mnt/media/videos`

The Jellyfin config and cache are stored in:

- `media-server/jellyfin/config`
- `media-server/jellyfin/cache`

## Services

### Jellyfin

Runs the media server and reuses your existing configuration folder.

### aria2

Handles torrent downloads and stores session state so downloads survive restarts.

### Jellyfin Downloader UI

Provides a browser UI for:

- adding magnet links
- organizing downloads
- deleting downloads
- uploading files directly into Movies or Videos

## Manual Uploads

The upload form supports two destinations:

- `Movie` saves into `/media/movies`
- `Video Library` saves into `/media/videos`

This is useful for content you already have locally and do not want to download through torrents.

## Getting Started

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Fill in the secret values in `.env`.

3. Make sure these host paths exist:

   - `/mnt/media/downloads`
   - `/mnt/media/movies`
   - `/mnt/media/tv`
   - `/mnt/media/videos`

4. Start the stack:

   ```bash
   docker compose up -d --build
   ```

5. Open the Jellyfin UI and create or verify your libraries:

   - Movies
   - TV Shows
   - Videos

## Notes On Migration

If you previously started Jellyfin with `docker run`, this Compose setup reuses the existing Jellyfin config folder instead of starting from scratch.

The important part is that the Jellyfin service mounts the top-level config directory:

```yaml
./media-server/jellyfin/config:/config
```

That prevents Jellyfin from seeing a mismatched config layout at startup.

## File Deletion Behavior

The downloader UI can remove torrents and their downloaded files from the host filesystem.

It also flushes the aria2 session after deletion so removed torrents do not reappear after a restart.

## Environment Variables

The sample `.env.example` includes:

- `TZ`
- `JELLYFIN_PUBLISHED_SERVER_URL`
- `ARIA2_SECRET`
- `JELLYFIN_API_KEY`
- `FLASK_SECRET_KEY`
- `DOWNLOADER_USERNAME`
- `DOWNLOADER_PASSWORD`

## Public Release Summary

This is a Docker Compose based Jellyfin media stack with torrent automation, manual uploads, and organized media folders for Movies, TV, and Videos.

It is built for a self-hosted home-lab workflow where you want Jellyfin, downloads, and file management in one place.

