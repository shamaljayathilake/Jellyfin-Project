import os
import re
import json
import time
import shutil
import threading
import urllib.request
import urllib.error

from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)

# Downloader UI authentication
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "")

DOWNLOADER_USERNAME = os.environ.get(
    "DOWNLOADER_USERNAME",
    "admin"
)

DOWNLOADER_PASSWORD = os.environ.get(
    "DOWNLOADER_PASSWORD",
    ""
)

ARIA2_URL = os.environ.get(
    "ARIA2_URL",
    "http://aria2:6800/jsonrpc"
)

ARIA2_SECRET = os.environ.get("ARIA2_SECRET", "")

JELLYFIN_URL = os.environ.get(
    "JELLYFIN_URL",
    "http://jellyfin:8096"
)

JELLYFIN_API_KEY = os.environ.get(
    "JELLYFIN_API_KEY",
    ""
)

DOWNLOADS = "/downloads"
MOVIES = "/media/movies"
TV = "/media/tv"


def aria2(method, params):
    data = json.dumps({
        "jsonrpc": "2.0",
        "id": "jellyfin-ui",
        "method": method,
        "params": params
    }).encode()

    req = urllib.request.Request(
        ARIA2_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read())

    if "error" in result:
        raise RuntimeError(result["error"])

    return result["result"]


def aria2_params(*params):
    if ARIA2_SECRET:
        return ["token:" + ARIA2_SECRET] + list(params)
    return list(params)


def jellyfin_refresh():
    if not JELLYFIN_API_KEY:
        return False

    url = JELLYFIN_URL.rstrip("/") + "/Library/Refresh"

    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Emby-Token": JELLYFIN_API_KEY
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status in (200, 202, 204)
    except Exception:
        return False


def translate_path(path):
    """
    Convert aria2's Docker path to the organizer container's path.
    """
    if path.startswith("/downloads/"):
        return "/downloads/" + path[len("/downloads/"):]
    return path


def delete_download_files(files):
    """Delete only files that aria2 placed below the downloads mount."""
    downloads_root = os.path.realpath(DOWNLOADS)
    removed = []

    for file_info in files:
        aria2_path = file_info.get("path", "")
        if not aria2_path:
            continue

        path = os.path.realpath(translate_path(aria2_path))

        try:
            inside_downloads = os.path.commonpath(
                [downloads_root, path]
            ) == downloads_root
        except ValueError:
            inside_downloads = False

        if not inside_downloads or path == downloads_root:
            continue

        if os.path.isfile(path) or os.path.islink(path):
            os.remove(path)
            removed.append(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
            removed.append(path)

        # Remove aria2's sidecar file when present.
        sidecar = path + ".aria2"
        if os.path.isfile(sidecar):
            os.remove(sidecar)
            removed.append(sidecar)

    # Remove empty task directories, but never the downloads root itself.
    parents = set()
    for path in removed:
        current = os.path.dirname(path)
        while current.startswith(downloads_root + os.sep):
            parents.add(current)
            current = os.path.dirname(current)

    for directory in sorted(parents, key=len, reverse=True):
        try:
            os.rmdir(directory)
        except OSError:
            pass

    return removed


def classify(filename):
    """
    Determine whether a video is a TV episode or movie.
    """
    if re.search(r"s\d{1,2}e\d{1,2}", filename, re.IGNORECASE):
        return "tv"

    return "movie"


def organize_download(gid):
    try:
        info = aria2(
            "aria2.tellStatus",
            aria2_params(gid)
        )

        if info.get("status") != "complete":
            return {
                "success": False,
                "message": "Download is not complete yet"
            }

        files = info.get("files", [])

        moved = []

        video_extensions = (
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".m4v",
            ".webm",
            ".wmv",
            ".ts"
        )

        for file_info in files:
            source = file_info.get("path", "")

            if not source:
                continue

            source = translate_path(source)

            if not os.path.exists(source):
                continue

            filename = os.path.basename(source)
            lower = filename.lower()

            if not lower.endswith(video_extensions):
                continue

            media_type = classify(filename)

            if media_type == "tv":
                destination_root = TV
            else:
                destination_root = MOVIES

            if media_type == "tv":
                match = re.search(
                    r"(s\d{1,2})e\d{1,2}",
                    filename,
                    re.IGNORECASE
                )

                if match:
                    season = int(
                        re.search(
                            r"s(\d{1,2})",
                            match.group(1),
                            re.IGNORECASE
                        ).group(1)
                    )

                    title = re.split(
                        r"\.S\d{1,2}E\d{1,2}",
                        filename,
                        flags=re.IGNORECASE
                    )[0]

                    title = re.sub(r"[._]+", " ", title).strip()

                    destination_dir = os.path.join(
                        destination_root,
                        title,
                        f"Season {season:02d}"
                    )
                else:
                    destination_dir = destination_root

            else:
                title = re.sub(
                    r"\.(19|20)\d{2}.*$",
                    "",
                    filename,
                    flags=re.IGNORECASE
                )

                title = os.path.splitext(title)[0]
                title = re.sub(r"[._]+", " ", title).strip()

                destination_dir = os.path.join(
                    destination_root,
                    title
                )

            os.makedirs(destination_dir, exist_ok=True)

            destination = os.path.join(
                destination_dir,
                filename
            )

            if os.path.abspath(source) == os.path.abspath(destination):
                continue

            if os.path.exists(destination):
                continue

            shutil.move(source, destination)
            moved.append(destination)

        if moved:
            jellyfin_refresh()

        return {
            "success": True,
            "moved": moved
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }



# ------------------------------------------------------------
# Authentication
# ------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if (
            username == DOWNLOADER_USERNAME
            and password == DOWNLOADER_PASSWORD
        ):
            session["authenticated"] = True
            return redirect(url_for("index"))

        return render_template(
            "login.html",
            error="Invalid username or password"
        )

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.before_request
def require_authentication():
    public_paths = {
        "/login",
        "/favicon.ico"
    }

    if request.path in public_paths:
        return None

    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required"}), 401

        return redirect(url_for("login"))

    return None

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/add", methods=["POST"])
def add_download():
    data = request.get_json(silent=True) or {}

    magnet = data.get("magnet", "").strip()

    if not magnet:
        return jsonify({
            "error": "Magnet link is required"
        }), 400

    if not magnet.startswith("magnet:?"):
        return jsonify({
            "error": "Invalid magnet link"
        }), 400

    try:
        gid = aria2(
            "aria2.addUri",
            aria2_params([magnet])
        )

        return jsonify({
            "success": True,
            "gid": gid
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/status")
def status():
    try:
        active = aria2(
            "aria2.tellActive",
            aria2_params()
        )

        waiting = aria2(
            "aria2.tellWaiting",
            aria2_params(0, 100)
        )

        stopped = aria2(
            "aria2.tellStopped",
            aria2_params(0, 100)
        )

        downloads = active + waiting + stopped

        result = []

        for item in downloads:
            total = int(item.get("totalLength", 0))
            completed = int(item.get("completedLength", 0))

            if total:
                progress = round(
                    completed * 100 / total,
                    1
                )
            else:
                progress = 0

            result.append({
                "gid": item.get("gid"),
                "status": item.get("status"),
                "name": item.get("bittorrent", {}).get(
                    "info", {}
                ).get("name")
                or item.get("files", [{}])[0].get(
                    "path", ""
                ).split("/")[-1],
                "completed": completed,
                "total": total,
                "progress": progress,
                "downloadSpeed": int(
                    item.get("downloadSpeed", 0)
                ),
                "uploadSpeed": int(
                    item.get("uploadSpeed", 0)
                ),
                "connections": int(
                    item.get("connections", 0)
                )
            })

        return jsonify({
            "downloads": result
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/organize/<gid>", methods=["POST"])
def organize(gid):
    result = organize_download(gid)
    return jsonify(result)


@app.route("/api/remove/<gid>", methods=["POST"])
def remove_download(gid):
    try:
        # Read the task first so its files can be removed after aria2 stops it.
        info = aria2("aria2.tellStatus", aria2_params(gid))
        status = info.get("status")

        if status in ("active", "waiting", "paused"):
            result = aria2(
                "aria2.forceRemove",
                aria2_params(gid)
            )
        else:
            result = aria2(
                "aria2.removeDownloadResult",
                aria2_params(gid)
            )

        removed = delete_download_files(info.get("files", []))

        return jsonify({
            "success": True,
            "result": result,
            "removed": removed
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500



# ------------------------------------------------------------
# Background auto-organizer
# ------------------------------------------------------------

PROCESSED_GIDS = set()
ORGANIZER_INTERVAL = 10


def auto_organizer():
    """
    Continuously watch aria2 for completed downloads and
    automatically organize media into the Jellyfin folders.
    """
    print("Auto-organizer started", flush=True)

    while True:
        try:
            downloads = aria2(
                "aria2.tellActive",
                aria2_params()
            )

            # Active downloads are handled below through the
            # global status check as well.
            complete = aria2(
                "aria2.tellStopped",
                aria2_params(0, 1000)
            )

            for info in complete:
                gid = info.get("gid")
                status = info.get("status")

                if not gid or status != "complete":
                    continue

                if gid in PROCESSED_GIDS:
                    continue

                files = info.get("files", [])

                # Only process GIDs containing actual video files.
                video_files = [
                    f for f in files
                    if f.get("path", "").lower().endswith(
                        (".mkv", ".mp4", ".avi", ".mov",
                         ".m4v", ".webm", ".wmv", ".ts")
                    )
                ]

                if not video_files:
                    # Metadata-only downloads are ignored.
                    PROCESSED_GIDS.add(gid)
                    continue

                print(
                    f"Auto-organizer: processing completed GID {gid}",
                    flush=True
                )

                try:
                    result = organize_download(gid)

                    if result.get("success"):
                        PROCESSED_GIDS.add(gid)
                        print(
                            f"Auto-organizer: GID {gid} organized: "
                            f"{result.get('moved', [])}",
                            flush=True
                        )
                    else:
                        print(
                            f"Auto-organizer: GID {gid} returned "
                            f"{result}",
                            flush=True
                        )

                except Exception as e:
                    print(
                        f"Auto-organizer ERROR for {gid}: {e}",
                        flush=True
                    )

        except Exception as e:
            print(
                f"Auto-organizer loop ERROR: {e}",
                flush=True
            )

        time.sleep(ORGANIZER_INTERVAL)


# Start the background organizer when the container starts.
organizer_thread = threading.Thread(
    target=auto_organizer,
    daemon=True,
    name="auto-organizer"
)

organizer_thread.start()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080
    )
