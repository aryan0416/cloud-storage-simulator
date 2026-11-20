"""
backup.py
---------
Backup and restore (simulates Azure Backup / point-in-time copies).

* create_backup  : copies a file into data/backups/ with a unique name
                   (timestamp + short UUID + original name).
* read_backup    : loads a backup's bytes (for download or restore).
* restore_backup : if the original file still exists it is overwritten;
                   if it was deleted it is re-created as a NEW file in the Hot tier.
"""

import uuid
from datetime import datetime

import auth
import config
import database
import storage
from storage import StorageError


def _backup_file_path(backup_record: dict):
    return storage.safe_join(config.BACKUP_DIR, backup_record["backup_path"])


def create_backup(file_id: int, user: dict) -> int:
    """Copy the current content of a file into the backups folder."""
    auth.require_permission(user, "backup")
    record = database.get_file(file_id)
    if record is None:
        raise StorageError("The selected file no longer exists.")

    # Read the file the same way a download would (handles Archive and outages).
    try:
        data, source = storage.read_file_for_download(record)
    except StorageError as exc:
        raise StorageError(f"Backup failed - {exc}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{timestamp}_{uuid.uuid4().hex[:8]}_{record['original_name']}"
    try:
        target = storage.safe_join(config.BACKUP_DIR, backup_name)
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        raise StorageError(f"Disk error while writing the backup: {exc}")

    backup_id = database.add_backup(file_id, record["original_name"], backup_name,
                                    len(data), user["username"])
    database.log_activity(user["username"], user["role"], "Backup created",
                          record["original_name"],
                          f"Backup #{backup_id} ({storage.format_size(len(data))}) read from {source} region")
    return backup_id


def read_backup(backup_id: int) -> tuple[dict, bytes]:
    """Return (backup_record, bytes). Raises StorageError if anything is missing."""
    backup_record = database.get_backup(backup_id)
    if backup_record is None:
        raise StorageError(f"Backup #{backup_id} was not found in the database.")
    try:
        return backup_record, _backup_file_path(backup_record).read_bytes()
    except FileNotFoundError:
        raise StorageError(
            f"Backup file '{backup_record['backup_path']}' is missing from data/backups/. "
            "It may have been removed outside the app."
        )
    except OSError as exc:
        raise StorageError(f"Could not read backup #{backup_id}: {exc}")


def backup_file_exists(backup_record: dict) -> bool:
    try:
        return _backup_file_path(backup_record).exists()
    except StorageError:
        return False


def original_still_exists(backup_record: dict) -> bool:
    return backup_record["file_id"] is not None and database.get_file(backup_record["file_id"]) is not None


def restore_backup(backup_id: int, user: dict) -> str:
    """Restore a backup and return a message describing what happened."""
    auth.require_permission(user, "restore")
    backup_record, data = read_backup(backup_id)

    if original_still_exists(backup_record):
        # Case 1: original file exists -> overwrite it with the backup content.
        file_record = storage.overwrite_file_content(backup_record["file_id"], data)
        database.log_activity(user["username"], user["role"], "Restore (overwrite)",
                              file_record["original_name"],
                              f"Overwritten with backup #{backup_id} from {backup_record['created_at']}")
        return f"'{file_record['original_name']}' was overwritten with backup #{backup_id}."

    # Case 2: original was deleted -> re-create it as a new Hot/LRS file.
    new_id = storage.upload_file(data, backup_record["original_name"], "Hot", "LRS", user,
                                 action="Restore (re-created)")
    if backup_record["file_id"] is not None:
        database.relink_backups(backup_record["file_id"], new_id)
    return (f"The original file had been deleted, so '{backup_record['original_name']}' "
            f"was re-created as a new file (id {new_id}) in the Hot tier.")
