# Cloud Storage and Backup Management Simulator

A college examination project that simulates **Azure Blob Storage** concepts from the
**AZ-900 (Microsoft Azure Fundamentals)** syllabus on a local computer.
Files are stored in local folders, metadata in SQLite, and the UI is built with Streamlit.
**No Azure account, credentials or paid/external services are used.**

---

## 1. Setup and run

Requires **Python 3.10+**.

### Windows (Command Prompt or PowerShell)

```bat
cd cloud-storage-simulator
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

> PowerShell: if activation is blocked, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `venv\Scripts\activate.bat` from Command Prompt.

### macOS / Linux

```bash
cd cloud-storage-simulator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The browser opens at **http://localhost:8501**. The database (`data/cloud_storage.db`),
the folders and the demo users are created automatically on first run.

To start again from a clean state, stop the app and delete the `data/` folder.

---

## 2. Demo login credentials

| Username      | Password     | Role (Azure RBAC) | Permissions |
|---------------|--------------|-------------------|-------------|
| `owner`       | `owner123`   | Owner             | Everything, including the Activity Log and "Load demo data" |
| `contributor` | `contrib123` | Contributor       | Upload, delete, change tier, rehydrate, back up, restore, outage simulation |
| `reader`      | `reader123`  | Reader            | View and download only |

Tip: log in as **owner** and press **Load demo data** on the Dashboard to get sample files instantly.

---

## 3. Architecture

```
                 +--------------------------------------------+
   Browser  ---> |  app.py  (Streamlit UI, pages, sidebar)    |
                 |  ui.py + assets/styles.css (presentation)  |
                 +------+--------------+--------------+-------+
                        |              |              |
                 +------v-----+  +-----v------+  +----v---------+
                 |  auth.py   |  | storage.py |  |  backup.py   | <-- demo_data.py
                 |  login,    |  | upload,    |  |  backup,     |     (generates sample
                 |  hashing,  |  | download,  |  |  restore     |      files in code)
                 |  RBAC      |  | tiers, GRS,|  +----+---------+
                 +------+-----+  | outage,    |       |
                        |        | costs      |       |
                        |        +--+-----+---+       |
                        |           |     |           |
                 +------v-----------v-+   |           |
                 |    database.py     |   |           |
                 |  SQLite (sqlite3), |   |           |
                 |  parameterised SQL |   |           |
                 +---------+----------+   |           |
                           |              |           |
        +------------------v--+  +--------v-----------v-------------------------+
        | data/cloud_storage  |  | Local filesystem ("the cloud")               |
        |        .db          |  |   data/storage/           primary region     |
        +---------------------+  |   data/secondary_region/  GRS paired region  |
                                 |   data/backups/           backup copies      |
                                 +----------------------------------------------+

        config.py  -- paths, quota, tier prices, roles, demo users (used by all modules)
```

### Module descriptions

| File | Responsibility |
|------|----------------|
| `app.py` | Streamlit UI: login page, sidebar navigation, one function per page, success/error messages. Contains no business logic. |
| `config.py` | All settings: folder paths (pathlib), 1 GB quota, tier prices and minimum periods, rehydration delay, redundancy multipliers, role permissions, demo users. |
| `database.py` | SQLite connection, table creation, and every query (parameterised with `?`). Also the activity log and simulator settings. |
| `auth.py` | PBKDF2-HMAC-SHA256 password hashing with a random salt, login check, demo-user seeding, and RBAC permission checks (`has_permission`, `require_permission`). |
| `storage.py` | Upload (sanitising, path-traversal protection, UUID names, quota check), download, delete, tier changes, early-deletion charges, Archive rehydration, LRS/GRS copies, outage simulation, cost calculations. |
| `backup.py` | Create backups (timestamp + UUID name), read/download backups, restore (overwrite existing file or re-create a deleted one in Hot). |
| `demo_data.py` | Owner-only demo loader: generates a .txt, .csv and .png chart (Pillow) in code and uploads them through the normal upload function, then creates one backup. |
| `ui.py` | Presentation helpers: CSS loader, page header, status badges, info panels, table helpers (pill columns) and the shared Plotly chart template. |
| `assets/styles.css` | The design system: CSS variables, sidebar, cards, badges, buttons, forms, tables, alerts, login card and responsive rules. |
| `.streamlit/config.toml` | Streamlit theme (colours, radius, dark sidebar), minimal toolbar, 1 GB upload limit. |

**Security in depth:** the UI hides or disables buttons a role cannot use, *and* every
back-end function calls `auth.require_permission()` again, so a forbidden action is
refused even if the UI were bypassed. Denied attempts are written to the activity log.

---

## 4. Database schema (`data/cloud_storage.db`)

```
users
  id INTEGER PK, username TEXT UNIQUE, password_hash TEXT, salt TEXT, role TEXT

files
  id INTEGER PK, original_name TEXT, stored_name TEXT (UUID_name on disk),
  size_bytes INTEGER, upload_date TEXT, tier TEXT, redundancy TEXT,
  tier_changed_at TEXT, rehydration_status TEXT ('None' | 'Rehydrating'),
  rehydrate_target TEXT, rehydrate_started_at TEXT, uploaded_by TEXT

backups
  id INTEGER PK, file_id INTEGER (original file id), original_name TEXT,
  backup_path TEXT (file name in data/backups/), size_bytes INTEGER,
  created_at TEXT, created_by TEXT

activity_log
  id INTEGER PK, timestamp TEXT, username TEXT, role TEXT,
  action TEXT, filename TEXT, details TEXT

settings
  key TEXT PK, value TEXT          -- e.g. primary_outage = '0' / '1'
```

---

## 5. Design system

The interface is styled like a cloud management console. All styling lives in
`assets/styles.css` (loaded once by `ui.load_css()`) and `.streamlit/config.toml`.
No external fonts, CDNs or CSS frameworks are used, so the app works fully offline.
Icons are Streamlit's built-in Material icons (`:material/name:`); the app uses no emojis.

| Token | Value |
|-------|-------|
| Primary / primary-dark / primary-soft | `#0F62FE` / `#0043CE` / `#E8F0FE` |
| Success / warning / danger | `#198038` / `#B28600` / `#DA1E28` |
| Text / muted / border | `#1B2333` / `#5D6B82` / `#E1E6EF` |
| Surface / page background / sidebar | `#FFFFFF` / `#F5F7FA` / `#0B1F3A` |
| Tier colours | Hot `#DA1E28`, Cool `#0F62FE`, Cold `#6929C4`, Archive `#6F6F6F` |
| Font stack | "Segoe UI", system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif |
| Spacing scale | 4, 8, 12, 16, 24, 32 px |
| Radius / shadow | 8px cards, 6px controls / `0 1px 3px rgba(16,24,40,0.08)` |

Components:
- **Sidebar**: dark navy, app name and subtitle, menu with a highlighted active page, region status, user card with role badge, logout button.
- **Page header**: 24px title, one-line description, thin divider. Streamlit's menu, footer and Deploy button are hidden.
- **Metric cards**: white cards with border, uppercase labels and equal height.
- **Badges** (`ui.badge()`): pills for tiers, redundancy, file status and roles. Tables show the same values as coloured pills through `st.column_config`.
- **Buttons**: primary (blue), secondary (white with border), destructive (red) for delete and "restore (overwrite)".
- **Alerts and info panels**: left colour border with a soft background; explanation panels have a heading.
- **Charts** (`ui.style_chart()`): one shared Plotly template, with transparent background, system font, muted gridlines, tier colours and the legend at the bottom.
- **Responsive**: below 900px, card rows wrap to two per row; below 600px they stack in a single column.

---

## 6. Features

1. **Login and roles (RBAC)** – three demo users; salted PBKDF2 hashes; Owner / Contributor / Reader; logout in the sidebar.
2. **Dashboard** – total files, storage used, capacity with % used, backups, estimated monthly cost; donut chart of storage per tier; bar chart of cost per tier; last 10 activities; Owner-only *Load demo data*.
3. **File Manager** – upload into Hot/Cool/Cold with LRS/GRS (Archive not allowed at upload); safe UUID filenames; path traversal rejected; quota enforced; table with readable sizes; download button per file; delete with confirmation (removes GRS copy too, keeps backups).
4. **Storage Tier Simulator** – illustrative prices; tier change; early-deletion warning and charge (remaining days × daily price), logged; Archive is offline with *Rehydrate to Hot/Cool*; rehydration completes after `REHYDRATION_SECONDS` (30 s) with a live progress bar.
5. **Redundancy Simulator** – LRS vs GRS (real secondary copy on disk); ZRS/GZRS explained; *Simulate primary region outage*: GRS files download from the secondary copy, LRS files become unavailable and writes are paused; *Restore primary region*.
6. **Backup Manager** – timestamp+UUID backup files; list with download buttons; restore with confirmation (overwrite, or re-create in Hot if deleted); clear errors if a backup file is missing.
7. **Cost Estimator** – current cost per tier and total (monthly/yearly); *what-if* calculator for any GB size with LRS vs GRS comparison chart (GRS = 2×).
8. **Activity Log** – every action stored; Owner-only page with user/action/filename filters and CSV export.
9. **AZ-900 Concepts** – table mapping each feature to the syllabus, including the shared responsibility model.
10. **Demo data** – generated in code, uploaded through the normal upload function.

### Quick demo script (for the viva)

1. Log in as **owner** -> Dashboard -> **Load demo data**.
2. File Manager -> download `demo_readme.txt`; upload your own file into **Cool**.
3. Storage Tiers -> move the Cool file to Hot -> see the **early-deletion warning**.
4. Move a file to **Archive** -> its download is blocked -> **Rehydrate to Hot** -> wait 30 s.
5. Redundancy -> **Simulate primary region outage** -> GRS files still download, LRS do not -> **Restore**.
6. Backups -> create a backup -> delete the file in File Manager -> **Restore** re-creates it in Hot.
7. Activity Log -> filter by action. Log out and log in as **reader** to show buttons are disabled.

---

## 7. AZ-900 concepts demonstrated

Blob access tiers · Archive rehydration · early deletion / minimum storage period ·
LRS, ZRS, GRS, GZRS redundancy · region pairs · Azure RBAC built-in roles ·
identity and authentication · backup and disaster recovery · cost management and pricing factors ·
Azure Monitor / Activity Log · shared responsibility model.

---

## 8. Limitations

- **Simulation only.** Nothing is sent to Azure; "regions" are local folders and tier changes only update the database.
- **Illustrative prices.** The prices in `config.py` are simplified examples, **not official Azure prices**. Real Azure also charges for transactions, data retrieval and egress, which are not modelled.
- Simulated LRS stores one copy (real LRS keeps three); GRS is simulated as one extra copy at 2× cost.
- Rehydration takes 30 seconds instead of up to 15 hours; rehydration completes when the app is next used.
- **Educational authentication, not production-grade security.** Demo passwords are published in this README, there is no user management, password reset, MFA, HTTPS or session expiry.
- Single-user local app: SQLite and session state are not designed for many simultaneous users.
- The storage quota counts primary data only (GRS secondary copies and backups are not counted).
