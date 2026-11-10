"""
ParkSight administration commands.

    python -m src.manage migrate
    python -m src.manage create-user --username admin --role admin
    python -m src.manage reset-password --username admin
    python -m src.manage import-legacy            # demo camera + data/parking_spaces.json
    python -m src.manage purge                    # apply the retention period now
"""

import argparse
import getpass
import json
import sys

from src import config, security
from src.database import Database
from src.logging_setup import configure_logging
from src.repositories import Conflict, Repositories


def _read_password(args):
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match.")
    problem = security.password_problem(password)
    if problem:
        sys.exit(problem)
    return password


def cmd_migrate(db, repos, args):
    applied = db.migrate()
    print("Applied: " + ", ".join(applied) if applied else "Database schema is up to date.")


def cmd_create_user(db, repos, args):
    db.migrate()
    user = repos.create_user(args.username, _read_password(args), args.role)
    print(f"Created {user['role']} '{user['username']}'.")


def cmd_reset_password(db, repos, args):
    user = repos.get_user_for_login(args.username)
    if not user:
        sys.exit(f"No user named '{args.username}'.")
    repos.update_user(user["id"], password=_read_password(args), active=True)
    print(f"Password for '{user['username']}' updated; existing sessions were signed out.")


def cmd_import_legacy(db, repos, args):
    """Create a camera + zone from the original single-camera configuration."""
    db.migrate()
    with open(args.spaces, "r", encoding="utf-8") as handle:
        polygons = json.load(handle)
    if not (config.VIDEO_DIR / args.video).is_file():
        sys.exit(f"Video '{args.video}' not found in {config.VIDEO_DIR}.")

    import cv2

    cap = cv2.VideoCapture(str(config.VIDEO_DIR / args.video))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    try:
        camera = repos.create_camera({
            "name": args.camera_name, "location": "Demonstration video", "source_type": "file",
            "source_url": args.video, "username": None, "password": None,
            "rtsp_transport": "tcp", "enabled": True,
        })
        zone = repos.create_zone({"camera_id": camera["id"], "name": args.zone_name, "area": args.area})
    except Conflict as error:
        sys.exit(f"{error}. Nothing imported.")
    spaces = [{"label": f"P{i + 1}", "polygon": polygon} for i, polygon in enumerate(polygons)]
    repos.save_layout(zone["id"], width, height, spaces)
    print(f"Imported camera '{camera['name']}', zone '{zone['name']}' with {len(spaces)} spaces.")


def cmd_purge(db, repos, args):
    days = repos.get_settings().retention_days
    print(f"Deleted {db.purge_expired(days)} history rows older than {days} days.")


def main(argv=None):
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m src.manage")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply database migrations")

    for name in ("create-user", "reset-password"):
        p = sub.add_parser(name)
        p.add_argument("--username", required=True)
        p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
        if name == "create-user":
            p.add_argument("--role", choices=["admin", "viewer"], default="viewer")

    p = sub.add_parser("import-legacy", help="import data/parking_spaces.json as a demo camera")
    p.add_argument("--spaces", default=config.SPACES_PATH)
    p.add_argument("--video", default="parking.mp4", help="file name inside the video directory")
    p.add_argument("--camera-name", default="Demo camera")
    p.add_argument("--zone-name", default="Zone A")
    p.add_argument("--area", default="Ground level")

    sub.add_parser("purge", help="delete history older than the retention period")

    args = parser.parse_args(argv)
    db = Database()
    repos = Repositories(db)
    handler = {
        "migrate": cmd_migrate,
        "create-user": cmd_create_user,
        "reset-password": cmd_reset_password,
        "import-legacy": cmd_import_legacy,
        "purge": cmd_purge,
    }[args.command]
    try:
        handler(db, repos, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
