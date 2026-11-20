"""
storage.py
----------
Simulated Azure Blob Storage running on the local filesystem.

What this module does:
* Upload, download and delete files ("blobs").
* Access tiers (Hot / Cool / Cold / Archive), tier changes and the
  early-deletion charge rule.
* Archive rehydration (simulated with a short timer).
* Redundancy: LRS keeps one copy in data/storage/, GRS keeps an extra copy
  in data/secondary_region/.
* Primary-region outage simulation (GRS files stay readable from the secondary).
* Cost calculations used by the dashboard and the cost estimator.

Every public function that changes data first checks the user's permission
(auth.require_permission) and writes an entry to the activity log.
"""

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import auth
import config
import database


class StorageError(Exception):
    """A friendly, user-facing error raised by storage operations."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def format_size(size_bytes: int | float) -> str:
    """Turn a byte count into a readable string, e.g. 2048 -> '2.00 KB'."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def format_usd(amount: float) -> str:
    """Money as text. Tiny amounts (small demo files) keep 10 decimals so they are not shown as $0."""
    if amount == 0:
        return "$0.00"
    if amount < 0.01:
        return f"${amount:.10f}".rstrip("0")
    return f"${amount:,.4f}"


def bytes_to_gb(size_bytes: int | float) -> float:
    return size_bytes / (1024 ** 3)


def parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def sanitize_filename(name: str) -> str:
    """
    Make an uploaded filename safe to store.
    * Rejects path traversal and folder separators (e.g. '../secret.txt').
    * Replaces unusual characters with '_'.
    * Removes leading dots (hidden files) and limits the length.
    """
    if not name or not name.strip():
        raise StorageError("The file name is empty.")
    name = name.strip()

    # Reject anything that looks like a path instead of a plain file name.
    if re.search(r"[\\/]", name) or name in {".", ".."} or name.startswith(".."):
        raise StorageError(
            f"Rejected file name '{name}': folder paths and '../' (path traversal) are not allowed."
        )

    clean = re.sub(r"[^A-Za-z0-9._-]", "_", name)   # keep letters, digits, . _ -
    clean = re.sub(r"_+", "_", clean)                # collapse '___' into '_'
    clean = clean.lstrip(".")                         # no hidden files
    if not clean:
        raise StorageError(f"File name '{name}' has no valid characters.")

    # Shorten very long names but keep the extension.
    if len(clean) > config.MAX_FILENAME_LENGTH:
        stem, dot, ext = clean.rpartition(".")
        if dot and len(ext) <= 10:
            clean = stem[: config.MAX_FILENAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            clean = clean[: config.MAX_FILENAME_LENGTH]
    return clean


def safe_join(base_dir: Path, file_name: str) -> Path:
    """Join base_dir + file_name and make sure the result stays INSIDE base_dir."""
    base = base_dir.resolve()
    target = (base / file_name).resolve()
    if base not in target.parents:
        raise StorageError("Blocked an attempt to access a path outside the storage folder.")
    return target


def primary_path(file_record: dict) -> Path:
    return safe_join(config.STORAGE_DIR, file_record["stored_name"])


def secondary_path(file_record: dict) -> Path:
    return safe_join(config.SECONDARY_DIR, file_record["stored_name"])


def _get_file_or_fail(file_id: int) -> dict:
    record = database.get_file(file_id)
    if record is None:
        raise StorageError(f"File with id {file_id} was not found. It may have been deleted.")
    return record


def _log(user: dict, action: str, filename: str = "", details: str = "") -> None:
    database.log_activity(user["username"], user["role"], action, filename, details)


# ---------------------------------------------------------------------------
# Primary region outage simulation
# ---------------------------------------------------------------------------
def is_outage_active() -> bool:
    return database.get_setting("primary_outage", "0") == "1"


def set_outage(active: bool, user: dict) -> None:
    auth.require_permission(user, "simulate_outage")
    database.set_setting("primary_outage", "1" if active else "0")
    if active:
        _log(user, "Outage simulated", details=f"{config.PRIMARY_REGION_NAME} marked as unavailable")
    else:
        _log(user, "Primary restored", details=f"{config.PRIMARY_REGION_NAME} back online")


def _ensure_primary_writable() -> None:
    """Writes go to the primary region, so they fail while it is 'down'."""
    if is_outage_active():
        raise StorageError(
            "The primary region is down (outage simulation). Write operations are "
            "paused until the primary region is restored on the Redundancy page."
        )


# ---------------------------------------------------------------------------
# Cost and early-deletion calculations
# ---------------------------------------------------------------------------
def monthly_cost(size_bytes: int, tier: str, redundancy: str = "LRS") -> float:
    """Illustrative monthly storage cost in USD (GRS = 2 copies = 2x cost)."""
    price = config.TIERS[tier]["price_per_gb_month"]
    multiplier = config.REDUNDANCY[redundancy]["cost_multiplier"]
    return bytes_to_gb(size_bytes) * price * multiplier


def days_in_current_tier(file_record: dict) -> float:
    elapsed = datetime.now() - parse_time(file_record["tier_changed_at"])
    return elapsed.total_seconds() / 86400


def early_deletion_info(file_record: dict) -> tuple[float, float]:
    """
    Early-deletion rule: if a file leaves a tier before its minimum storage
    period, the remaining days are still charged.
        charge = remaining days x daily price of the tier (x2 for GRS)
    Returns (remaining_days, charge_in_usd).
    """
    tier = config.TIERS[file_record["tier"]]
    remaining_days = max(0.0, tier["min_days"] - days_in_current_tier(file_record))
    daily_cost = monthly_cost(file_record["size_bytes"], file_record["tier"],
                              file_record["redundancy"]) / config.DAYS_PER_MONTH
    return remaining_days, remaining_days * daily_cost


def _log_early_deletion(user: dict, file_record: dict, reason: str) -> float:
    """Record an early-deletion charge in the activity log, if there is one."""
    remaining_days, charge = early_deletion_info(file_record)
    if remaining_days > 0:
        _log(user, "Early deletion charge", file_record["original_name"],
             f"{reason} from {file_record['tier']} with {remaining_days:.1f} days left "
             f"of the {config.TIERS[file_record['tier']]['min_days']}-day minimum. "
             f"Simulated charge: {format_usd(charge)}")
    return charge


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def upload_file(data: bytes, original_name: str, tier: str, redundancy: str,
                user: dict, action: str = "Upload") -> int:
    """Save a new file in the simulated primary region (and secondary for GRS)."""
    auth.require_permission(user, "upload")
    _ensure_primary_writable()

    if tier not in config.UPLOAD_TIERS:
        raise StorageError(
            f"Files cannot be uploaded straight into the {tier} tier. "
            f"Choose one of: {', '.join(config.UPLOAD_TIERS)}."
        )
    if redundancy not in config.REDUNDANCY:
        raise StorageError(f"Unknown redundancy option '{redundancy}'.")
    if not data:
        raise StorageError("The file is empty (0 bytes) and was not uploaded.")

    safe_name = sanitize_filename(original_name)

    # Quota check: used + new file must fit in the storage account.
    used = database.get_total_size()
    if used + len(data) > config.STORAGE_QUOTA_BYTES:
        raise StorageError(
            f"Upload rejected: quota exceeded. Used {format_size(used)} of "
            f"{format_size(config.STORAGE_QUOTA_BYTES)}; this file needs {format_size(len(data))}."
        )

    # Unique internal name: UUID + sanitised name, so two 'report.txt' never collide.
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    record = {"stored_name": stored_name}
    written: list[Path] = []
    try:
        target = primary_path(record)
        target.write_bytes(data)
        written.append(target)
        if redundancy == "GRS":
            copy = secondary_path(record)
            copy.write_bytes(data)
            written.append(copy)
        file_id = database.add_file(safe_name, stored_name, len(data),
                                    tier, redundancy, user["username"])
    except Exception as exc:
        for path in written:                 # undo partial writes
            path.unlink(missing_ok=True)
        raise StorageError(f"Could not save '{safe_name}': {exc}") from exc

    _log(user, action, safe_name,
         f"{format_size(len(data))}, tier {tier}, redundancy {redundancy}")
    return file_id


# ---------------------------------------------------------------------------
# Download / availability
# ---------------------------------------------------------------------------
def get_availability(file_record: dict) -> tuple[bool, str]:
    """
    Can this file be downloaded right now? Returns (available, explanation).
    """
    if file_record["rehydration_status"] == "Rehydrating":
        return False, f"Rehydrating to {file_record['rehydrate_target']} (offline)"
    if not config.TIERS[file_record["tier"]]["online"]:
        return False, "Archive tier is offline - rehydrate first"
    if is_outage_active():
        if file_record["redundancy"] == "GRS":
            return True, "Served from secondary region (GRS)"
        return False, "Unavailable - primary region down (LRS has no copy elsewhere)"
    return True, "Served from primary region"


def read_file_for_download(file_record: dict) -> tuple[bytes, str]:
    """
    Return (file_bytes, source) or raise StorageError.
    During an outage GRS files are read from the secondary region.
    """
    available, reason = get_availability(file_record)
    if not available:
        raise StorageError(f"'{file_record['original_name']}' cannot be downloaded: {reason}.")

    if is_outage_active():
        path, source = secondary_path(file_record), "secondary"
    else:
        path, source = primary_path(file_record), "primary"

    try:
        return path.read_bytes(), source
    except FileNotFoundError:
        raise StorageError(
            f"The stored data for '{file_record['original_name']}' is missing from the "
            f"{source} region folder."
        )
    except OSError as exc:
        raise StorageError(f"Could not read '{file_record['original_name']}': {exc}")


def log_download(user: dict, file_name: str, source: str) -> None:
    """Called by the download button's on_click callback."""
    _log(user, "Download", file_name, f"Downloaded from {source} region")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
def delete_file(file_id: int, user: dict) -> float:
    """Delete the file, its GRS copy and its DB record. Backups are kept.
    Returns the simulated early-deletion charge (0 if none)."""
    auth.require_permission(user, "delete")
    _ensure_primary_writable()
    record = _get_file_or_fail(file_id)
    if record["rehydration_status"] == "Rehydrating":
        raise StorageError("This file is being rehydrated. Wait until it finishes before deleting.")

    charge = _log_early_deletion(user, record, "Deleted")
    try:
        primary_path(record).unlink(missing_ok=True)
        secondary_path(record).unlink(missing_ok=True)
        database.delete_file_record(file_id)
    except OSError as exc:
        raise StorageError(f"Could not delete '{record['original_name']}': {exc}")

    _log(user, "Delete", record["original_name"],
         f"Removed from storage{' and secondary region' if record['redundancy'] == 'GRS' else ''}. "
         f"Backups kept.")
    return charge


# ---------------------------------------------------------------------------
# Tier changes and rehydration
# ---------------------------------------------------------------------------
def change_tier(file_id: int, new_tier: str, user: dict) -> float:
    """Move a file between Hot / Cool / Cold / Archive.
    Returns the simulated early-deletion charge for leaving the old tier."""
    auth.require_permission(user, "change_tier")
    _ensure_primary_writable()
    record = _get_file_or_fail(file_id)

    if new_tier not in config.TIERS:
        raise StorageError(f"Unknown tier '{new_tier}'.")
    if record["rehydration_status"] == "Rehydrating":
        raise StorageError("This file is already being rehydrated.")
    if record["tier"] == new_tier:
        raise StorageError(f"'{record['original_name']}' is already in the {new_tier} tier.")
    if record["tier"] == "Archive":
        raise StorageError("Archive files must be rehydrated (use the Rehydrate buttons).")

    charge = _log_early_deletion(user, record, "Moved")
    database.update_file_tier(file_id, new_tier)
    _log(user, "Tier change", record["original_name"], f"{record['tier']} -> {new_tier}")
    return charge


def start_rehydration(file_id: int, target_tier: str, user: dict) -> float:
    """Begin (simulated) rehydration of an Archive file to Hot or Cool."""
    auth.require_permission(user, "rehydrate")
    _ensure_primary_writable()
    record = _get_file_or_fail(file_id)

    if record["tier"] != "Archive":
        raise StorageError("Only Archive files need rehydration.")
    if record["rehydration_status"] == "Rehydrating":
        raise StorageError("Rehydration is already in progress for this file.")
    if target_tier not in config.REHYDRATE_TARGETS:
        raise StorageError(f"Archive files can only be rehydrated to {' or '.join(config.REHYDRATE_TARGETS)}.")

    charge = _log_early_deletion(user, record, "Rehydrated")
    database.set_rehydrating(file_id, target_tier)
    _log(user, "Rehydration started", record["original_name"],
         f"Archive -> {target_tier}; completes in {config.REHYDRATION_SECONDS} s (simulated)")
    return charge


def rehydration_seconds_left(file_record: dict) -> int:
    if file_record["rehydration_status"] != "Rehydrating" or not file_record["rehydrate_started_at"]:
        return 0
    finish = parse_time(file_record["rehydrate_started_at"]) + timedelta(seconds=config.REHYDRATION_SECONDS)
    return max(0, int((finish - datetime.now()).total_seconds()))


def process_rehydrations() -> list[str]:
    """
    Complete any rehydration whose timer has finished. Called on every page
    load, so no background thread is needed. Returns the completed file names.
    """
    completed = []
    for record in database.get_rehydrating_files():
        if rehydration_seconds_left(record) == 0:
            database.update_file_tier(record["id"], record["rehydrate_target"])
            database.log_activity("system", "-", "Rehydration completed", record["original_name"],
                                  f"Archive -> {record['rehydrate_target']}; file is online again")
            completed.append(record["original_name"])
    return completed


# ---------------------------------------------------------------------------
# Used by backup restore: overwrite an existing file's content
# ---------------------------------------------------------------------------
def overwrite_file_content(file_id: int, data: bytes) -> dict:
    """Replace a file's bytes (primary + GRS copy) and update its size."""
    _ensure_primary_writable()
    record = _get_file_or_fail(file_id)
    if record["tier"] == "Archive" or record["rehydration_status"] == "Rehydrating":
        raise StorageError("The current file is in the offline Archive tier. Rehydrate it before restoring.")

    used_without_file = database.get_total_size() - record["size_bytes"]
    if used_without_file + len(data) > config.STORAGE_QUOTA_BYTES:
        raise StorageError("Restore rejected: it would exceed the storage quota.")
    try:
        primary_path(record).write_bytes(data)
        if record["redundancy"] == "GRS":
            secondary_path(record).write_bytes(data)
    except OSError as exc:
        raise StorageError(f"Disk error while restoring '{record['original_name']}': {exc}")
    database.update_file_size(file_id, len(data))
    return record


# ---------------------------------------------------------------------------
# Summaries for the dashboard and cost estimator
# ---------------------------------------------------------------------------
def tier_summary() -> list[dict]:
    """Per tier: number of files, bytes used and monthly cost."""
    summary = {tier: {"Tier": tier, "Files": 0, "Bytes": 0, "Monthly cost ($)": 0.0}
               for tier in config.TIERS}
    for record in database.get_all_files():
        row = summary[record["tier"]]
        row["Files"] += 1
        row["Bytes"] += record["size_bytes"]
        row["Monthly cost ($)"] += monthly_cost(record["size_bytes"], record["tier"], record["redundancy"])
    return list(summary.values())


def total_monthly_cost() -> float:
    return sum(row["Monthly cost ($)"] for row in tier_summary())
