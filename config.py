"""
config.py
---------
Central configuration for the Cloud Storage and Backup Management Simulator.

Everything that a teacher might ask "where is this value defined?" lives here:
folder paths, storage quota, tier prices, redundancy rules, roles and demo users.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (pathlib makes these work on Windows, macOS and Linux)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = DATA_DIR / "storage"                    # simulated PRIMARY region
SECONDARY_DIR = DATA_DIR / "secondary_region"         # simulated GRS paired region
BACKUP_DIR = DATA_DIR / "backups"                     # backup copies
DB_PATH = DATA_DIR / "cloud_storage.db"               # SQLite database file

# Names shown in the UI for the two simulated regions (an Azure "region pair").
PRIMARY_REGION_NAME = "Central India (primary)"
SECONDARY_REGION_NAME = "South India (secondary pair)"

# ---------------------------------------------------------------------------
# Storage account limits
# ---------------------------------------------------------------------------
STORAGE_QUOTA_BYTES = 1 * 1024 ** 3        # 1 GB quota for the whole account
MAX_FILENAME_LENGTH = 100                   # longer names are shortened

# ---------------------------------------------------------------------------
# Blob access tiers
# ILLUSTRATIVE PRICES ONLY - these are NOT official Azure prices.
# price_per_gb_month : storage price in USD per GB per month
# min_days           : minimum storage period (early-deletion rule)
# online             : False means data is offline and must be rehydrated
# use                : short description shown on the Storage Tiers page
# ---------------------------------------------------------------------------
TIERS = {
    "Hot":     {"price_per_gb_month": 0.020,  "min_days": 0,   "online": True, "use": "Frequently accessed data"},
    "Cool":    {"price_per_gb_month": 0.010,  "min_days": 30,  "online": True, "use": "Infrequently accessed, kept 30+ days"},
    "Cold":    {"price_per_gb_month": 0.0045, "min_days": 90,  "online": True, "use": "Rarely accessed, kept 90+ days"},
    "Archive": {"price_per_gb_month": 0.002,  "min_days": 180, "online": False, "use": "Long-term retention, offline, 180+ days"},
}

# Tiers allowed when a file is first uploaded (Archive is not allowed directly).
UPLOAD_TIERS = ["Hot", "Cool", "Cold"]

# Tiers an Archive file can be rehydrated to.
REHYDRATE_TARGETS = ["Hot", "Cool"]

# Number of days in a month used for daily-price calculations.
DAYS_PER_MONTH = 30

# Simulated rehydration time in seconds (real Azure: up to 15 hours).
REHYDRATION_SECONDS = 30

# ---------------------------------------------------------------------------
# Redundancy options
# cost_multiplier: GRS keeps two copies, so we simulate it as 2x storage cost.
# ---------------------------------------------------------------------------
REDUNDANCY = {
    "LRS": {"name": "Locally Redundant Storage", "cost_multiplier": 1},
    "GRS": {"name": "Geo-Redundant Storage", "cost_multiplier": 2},
}

# ---------------------------------------------------------------------------
# Roles and permissions (simulates Azure RBAC built-in roles)
# ---------------------------------------------------------------------------
ROLE_PERMISSIONS = {
    "Owner": {
        "view", "download", "upload", "delete", "change_tier", "rehydrate",
        "backup", "restore", "simulate_outage", "view_activity_log",
        "load_demo_data",
    },
    "Contributor": {
        "view", "download", "upload", "delete", "change_tier", "rehydrate",
        "backup", "restore", "simulate_outage",
    },
    "Reader": {"view", "download"},
}

# Short human-readable description of each role (shown on the login page).
ROLE_DESCRIPTIONS = {
    "Owner": "Full access, including the activity log and demo data.",
    "Contributor": "Upload, delete, change tier, back up and restore files.",
    "Reader": "View and download files only.",
}

# Demo users created on first run. Passwords are HASHED before being stored.
DEMO_USERS = [
    {"username": "owner", "password": "owner123", "role": "Owner"},
    {"username": "contributor", "password": "contrib123", "role": "Contributor"},
    {"username": "reader", "password": "reader123", "role": "Reader"},
]

# Password hashing settings (PBKDF2 with SHA-256).
PBKDF2_ITERATIONS = 100_000
SALT_BYTES = 16

# Number of recent activity entries shown on the dashboard.
RECENT_ACTIVITY_LIMIT = 10
