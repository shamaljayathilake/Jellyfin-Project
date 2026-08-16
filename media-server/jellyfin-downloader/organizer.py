#!/usr/bin/env python3

import os
import re
import json
import time
import shutil
import urllib.request

BASE = "/opt/jellyfin-downloader"
QUEUE = f"{BASE}/queue/completed"
LOG = f"{BASE}/organizer.log"

ARIA2_URL = "http://127.0.0.1:6800/jsonrpc"
ARIA2_SECRET = os.environ.get("ARIA2_SECRET", "")

JELLYFIN_URL = os.environ.get(
    "JELLYFIN_URL",
    "http://127.0.0.1:8096"
)
JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")

MOVIES = "/mnt/media/movies"
TV = "/mnt/media/tv"

VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".m4v",
    ".webm",
    ".wmv",
    ".ts",
)


def log(message):
    with open(LOG, "a") as f:
        f.write(
            time.strftime("%Y-%m-%d %H:%M:%S")
            + " "
            + message
            + "\n"
        )


def aria2(method, params):
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "organizer",
        "method": method,
        "params": params
    }).encode()

    request = urllib.request.Request(
        ARIA2_URL,
        data=payload,
        headers={
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read())

    if "error" in result:
        raise RuntimeError(result["error"])

    return result["result"]


def host_path(path):
    if path.startswith("/downloads/"):
        return "/mnt/media/downloads/" + path[len("/downloads/"):]

    return path


def jellyfin_refresh():
    if not JELLYFIN_API_KEY:
        log("WARNING: JELLYFIN_API_KEY is not configured")
        return

    url = JELLYFIN_URL.rstrip("/") + "/Library/Refresh"

    request = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Emby-Token": JELLYFIN_API_KEY
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            log(
                f"Jellyfin library refresh triggered: "
                f"HTTP {response.status}"
            )
    except Exception as e:
        log(f"Jellyfin refresh ERROR: {e}")


def clean_name(name):
    """
    Convert release-style names into reasonable Jellyfin names.
    """

    name = name.replace(".", " ")
    name = name.replace("_", " ")
    name = re.sub(r"\s+", " ", name)

    return name.strip(" .-_")


def detect_tv(filename):
    match = re.search(
        r"(?i)s(\d{1,2})e(\d{1,2})",
        filename
    )

    if not match:
        return None

    season = int(match.group(1))
    episode = int(match.group(2))

    return season, episode


def detect_movie_year(name):
    match = re.search(
        r"(?<!\d)((?:19|20)\d{2})(?!\d)",
        name
    )

    if match:
        return int(match.group(1))

    return None


def get_tv_show_name(torrent_dir, filename):
    """
    Example:

    Reacher.S04E01.1080p.x265-ELiTE

    becomes:

    Reacher
    """

    torrent_name = os.path.basename(torrent_dir)

    match = re.search(
        r"(?i)(.*?)\.?S\d{1,2}E\d{1,2}",
        torrent_name
    )

    if match:
        name = match.group(1)
    else:
        match = re.search(
            r"(?i)(.*?)\.?S\d{1,2}",
            torrent_name
        )

        if match:
            name = match.group(1)
        else:
            name = torrent_name

    return clean_name(name)


def get_movie_name(torrent_dir, filename):
    """
    Example:

    The.Movie.2025.1080p.x265-GROUP

    becomes:

    The Movie (2025)
    """

    torrent_name = os.path.basename(torrent_dir)

    year = detect_movie_year(torrent_name)

    if year:
        before_year = torrent_name.split(str(year), 1)[0]
        title = clean_name(before_year)

        return f"{title} ({year})"

    # Fall back to filename
    filename_without_ext = os.path.splitext(filename)[0]

    year = detect_movie_year(filename_without_ext)

    if year:
        before_year = filename_without_ext.split(
            str(year),
            1
        )[0]

        title = clean_name(before_year)

        return f"{title} ({year})"

    return clean_name(torrent_name)


def cleanup_download_directory(directory, gid):
    """
    Delete leftover release files/directories after
    the media file has been successfully moved.
    """

    if not os.path.isdir(directory):
        return

    try:
        for root, dirs, files in os.walk(
            directory,
            topdown=False
        ):

            for filename in files:
                path = os.path.join(root, filename)

                try:
                    os.remove(path)
                    log(
                        f"GID {gid}: removed leftover file: "
                        f"{path}"
                    )
                except Exception as e:
                    log(
                        f"GID {gid}: unable to remove "
                        f"{path}: {e}"
                    )

            for dirname in dirs:
                path = os.path.join(root, dirname)

                try:
                    os.rmdir(path)
                except OSError:
                    pass

        try:
            os.rmdir(directory)
            log(
                f"GID {gid}: removed download directory: "
                f"{directory}"
            )
        except OSError:
            pass

    except Exception as e:
        log(
            f"GID {gid}: cleanup ERROR: {e}"
        )


def remove_aria2_download(gid):
    try:
        aria2(
            "aria2.removeDownloadResult",
            [
                "token:" + ARIA2_SECRET,
                gid
            ]
        )

        log(
            f"GID {gid}: removed completed result from aria2"
        )

    except Exception as e:
        log(
            f"GID {gid}: aria2 cleanup skipped: {e}"
        )


def process_gid(gid):
    log(f"Processing GID {gid}")

    info = aria2(
        "aria2.tellStatus",
        [
            "token:" + ARIA2_SECRET,
            gid
        ]
    )

    status = info.get("status")

    if status != "complete":
        log(
            f"GID {gid} is not complete: {status}"
        )
        return False

    files = info.get("files", [])

    if not files:
        raise RuntimeError(
            "aria2 returned no files"
        )

    video_moved = False
    download_directories = set()

    for file_info in files:

        aria2_source = file_info.get("path", "")

        source = host_path(aria2_source)

        log(
            f"GID {gid}: "
            f"aria2 path={aria2_source} "
            f"host path={source}"
        )

        if not os.path.exists(source):
            log(
                f"GID {gid}: source does not exist: "
                f"{source}"
            )
            continue

        filename = os.path.basename(source)

        if not filename.lower().endswith(
            VIDEO_EXTENSIONS
        ):
            log(
                f"GID {gid}: skipping non-video file: "
                f"{filename}"
            )
            continue

        torrent_dir = os.path.dirname(source)

        download_directories.add(torrent_dir)

        tv_info = detect_tv(filename)

        if tv_info:

            season, episode = tv_info

            show_name = get_tv_show_name(
                torrent_dir,
                filename
            )

            destination_dir = os.path.join(
                TV,
                show_name,
                f"Season {season:02d}"
            )

            media_type = "TV"

        else:

            movie_name = get_movie_name(
                torrent_dir,
                filename
            )

            destination_dir = os.path.join(
                MOVIES,
                movie_name
            )

            media_type = "Movie"

        os.makedirs(
            destination_dir,
            exist_ok=True
        )

        destination = os.path.join(
            destination_dir,
            filename
        )

        if os.path.exists(destination):

            log(
                f"GID {gid}: destination already exists: "
                f"{destination}"
            )

            video_moved = True
            continue

        log(
            f"GID {gid}: moving {media_type}: "
            f"{source} -> {destination}"
        )

        shutil.move(
            source,
            destination
        )

        log(
            f"GID {gid}: moved successfully: "
            f"{destination}"
        )

        video_moved = True

    if not video_moved:
        log(
            f"GID {gid}: no video file was moved"
        )
        return False

    # Clean up release directory
    for directory in download_directories:
        cleanup_download_directory(
            directory,
            gid
        )

    # Refresh Jellyfin
    jellyfin_refresh()

    # Remove completed result from aria2
    remove_aria2_download(gid)

    return True


def main():

    log("Jellyfin organizer started")

    while True:

        if os.path.exists(QUEUE):

            with open(QUEUE, "r") as f:
                gids = [
                    line.strip()
                    for line in f
                    if line.strip()
                ]

            remaining = []

            for gid in gids:

                try:

                    success = process_gid(gid)

                    if not success:
                        remaining.append(gid)

                except Exception as e:

                    log(
                        f"GID {gid} ERROR: {e}"
                    )

                    remaining.append(gid)

            # Write queue atomically
            temp_queue = QUEUE + ".tmp"

            with open(temp_queue, "w") as f:
                for gid in remaining:
                    f.write(gid + "\n")

            os.replace(
                temp_queue,
                QUEUE
            )

        time.sleep(10)


if __name__ == "__main__":
    main()
