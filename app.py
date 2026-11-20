"""
app.py
------
Streamlit user interface for the Cloud Storage and Backup Management Simulator.

Run with:   streamlit run app.py

How the app is organised:
* main()                 -> starts the database, handles login and the sidebar.
* one function per page  -> dashboard_page(), file_manager_page(), ...
* flash messages         -> success/error messages are stored in
                            st.session_state so they survive st.rerun().

This file only contains UI code. The real work happens in storage.py,
backup.py, auth.py and database.py. Shared styling helpers live in ui.py and
the design system (colours, spacing, components) in assets/styles.css.
"""

import mimetypes

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import backup
import config
import database
import demo_data
import storage
import ui
from storage import StorageError, format_size, format_usd

PAGES = list(ui.ICONS.keys())

# Colours for the "pill" columns in tables.
STATUS_COLOURS = {"Online": "#198038", "Offline": "#6F6F6F", "Rehydrating": "#B28600",
                  "Unavailable": "#DA1E28", "Complete": "#198038"}
YES_NO_COLOURS = {"Exists": "#198038", "Deleted": "#6F6F6F", "Present": "#198038", "Missing": "#DA1E28"}
DATETIME = st.column_config.DatetimeColumn
DATE_FORMAT = "YYYY-MM-DD HH:mm:ss"


# ---------------------------------------------------------------------------
# Page setup and styling
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Cloud Storage Simulator", page_icon=":material/cloud:", layout="wide")
ui.load_css()


# ---------------------------------------------------------------------------
# Flash messages + safe action helper
# ---------------------------------------------------------------------------
def flash(kind: str, message: str) -> None:
    """Queue a message (success / error / warning / info) for the next run."""
    st.session_state.setdefault("flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind)(message, icon=ui.ALERT_ICONS[kind])


def attempt(action, *args):
    """
    Run a back-end function and turn any error into a red error message.
    Returns (ok, result).
    """
    try:
        return True, action(*args)
    except (StorageError, PermissionError) as exc:
        flash("error", str(exc))
    except Exception as exc:                      # unexpected problem - still don't crash
        flash("error", f"Unexpected error: {exc}")
    return False, None


def current_user() -> dict:
    return st.session_state["user"]


def can(permission: str) -> bool:
    return auth.has_permission(current_user(), permission)


def no_permission(action_text: str) -> None:
    role = current_user()["role"]
    st.info(f"Your role (**{role}**) cannot {action_text}. "
            "Log in as Owner or Contributor to try this feature.", icon=":material/lock:")


def guess_mime(file_name: str) -> str:
    return mimetypes.guess_type(file_name)[0] or "application/octet-stream"


def charge_message(charge: float, file_name: str, tier: str) -> None:
    if charge > 0:
        flash("warning", f"Early deletion: '{file_name}' left the {tier} tier before its "
                         f"minimum period. Simulated charge **{format_usd(charge)}** (recorded in the activity log).")


def file_status(file_record: dict) -> str:
    """Short status word for badges: Online / Offline / Rehydrating / Unavailable."""
    if file_record["rehydration_status"] == "Rehydrating":
        return "Rehydrating"
    if file_record["tier"] == "Archive":
        return "Offline"
    available, _ = storage.get_availability(file_record)
    return "Online" if available else "Unavailable"


def section(title: str) -> None:
    st.subheader(title, anchor=False)


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------
def login_page() -> None:
    with st.container(key="login_card"):
        ui.html_block("<div class='login-brand'><div class='name'>Cloud Storage Simulator</div>"
                      "<div class='sub'>Azure Blob Storage concepts (AZ-900), simulated locally</div></div>")
        show_flash()
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch",
                                              icon=":material/login:")
        if submitted:
            user = auth.authenticate(username, password)
            if user:
                st.session_state["user"] = user
                flash("success", f"Welcome, {user['username']}. You are signed in as {user['role']}.")
                st.rerun()
            else:
                st.error("Invalid username or password.", icon=ui.ALERT_ICONS["error"])

        rows = "".join(
            f"<tr><td><code>{u['username']}</code></td><td><code>{u['password']}</code></td>"
            f"<td>{ui.badge(u['role'])}</td></tr>"
            for u in config.DEMO_USERS
        )
        ui.html_block("<div class='demo-box'><b>Demo accounts</b> (role-based access, like Azure RBAC)"
                      f"<table><tr><th>Username</th><th>Password</th><th>Role</th></tr>{rows}</table></div>")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def sidebar() -> str:
    user = current_user()
    with st.sidebar:
        ui.html_block("<div class='sidebar-brand'><div class='name'>Cloud Storage Simulator</div>"
                      "<div class='sub'>Azure Blob Storage simulation</div></div>"
                      "<div class='sidebar-label'>Navigation</div>")
        choice = st.radio("Navigation", PAGES, key="nav", label_visibility="collapsed", width="stretch",
                          format_func=lambda p: f"{ui.ICONS[p]}  {p}")

        if storage.is_outage_active():
            status = "<span class='dot down'></span>Primary region: outage (simulated)"
        else:
            status = "<span class='dot ok'></span>Primary region: online"
        ui.html_block(f"<div class='sidebar-label'>Status</div><div class='region-status'>{status}</div>")

        ui.html_block(f"<div class='user-card'><div class='uname'>{user['username']}</div>"
                      f"<div class='urole'>{ui.badge(user['role'])}</div></div>")
        if st.button("Log out", width="stretch", icon=":material/logout:", key="logout"):
            database.log_activity(user["username"], user["role"], "Logout")
            st.session_state.clear()
            flash("info", "You have been logged out.")
            st.rerun()
        ui.html_block("<div class='sidebar-note'>Educational simulation. No real cloud services are used.</div>")
    return choice


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def activity_table(entries: list[dict], height: int | str = "auto") -> None:
    df = pd.DataFrame(entries).drop(columns=["id"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["role"] = ui.as_pills(df["role"].replace("-", ""))
    df = df.rename(columns={"timestamp": "Timestamp", "username": "User", "role": "Role",
                            "action": "Action", "filename": "File", "details": "Details"})
    ui.table(df, {
        "Timestamp": DATETIME("Timestamp", format=DATE_FORMAT),
        "Role": ui.pill_column("Role", ui.ROLE_COLOURS),
        "Details": st.column_config.TextColumn("Details", width="large"),
    }, height=height)


def dashboard_page() -> None:
    ui.page_header("Dashboard", "Overview of your simulated storage account")
    show_flash()
    files = database.get_all_files()
    used = database.get_total_size()
    quota = config.STORAGE_QUOTA_BYTES
    percent = used / quota * 100

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total files", len(files))
    c2.metric("Storage used", format_size(used))
    c3.metric("Capacity", format_size(quota), f"{percent:.4f}% used", delta_color="off", delta_arrow="off")
    c4.metric("Backups", database.count_backups())
    cost = storage.total_monthly_cost()
    c5.metric("Est. monthly cost", f"${cost:,.2f}" if cost >= 0.01 or cost == 0 else "< $0.01",
              help=f"Exact illustrative cost: {format_usd(cost)} per month")
    st.progress(min(percent / 100, 1.0), text=f"Quota usage: {percent:.4f}%")

    summary = pd.DataFrame(storage.tier_summary())
    left, right = st.columns(2, gap="medium")
    with left:
        section("Storage used per tier")
        used_tiers = summary[summary["Bytes"] > 0]
        if used_tiers.empty:
            st.info("No files yet. Upload a file in the File Manager.", icon=ui.ALERT_ICONS["info"])
        else:
            fig = px.pie(used_tiers, names="Tier", values="Bytes", hole=0.55,
                         color="Tier", color_discrete_map=ui.TIER_COLOURS)
            fig.update_traces(hovertemplate="%{label}: %{value} bytes<extra></extra>",
                              marker=dict(line=dict(color="#FFFFFF", width=2)))
            ui.plotly_chart(ui.style_chart(fig))
    with right:
        section("Estimated monthly cost per tier")
        fig = px.bar(summary, x="Tier", y="Monthly cost ($)", color="Tier",
                     color_discrete_map=ui.TIER_COLOURS, text_auto=".3g")
        fig.update_layout(showlegend=False)
        if summary["Monthly cost ($)"].max() < 0.01:          # tiny demo costs: scientific axis labels
            fig.update_yaxes(tickformat=".1e")
        ui.plotly_chart(ui.style_chart(fig))

    section("Recent activity")
    recent = database.get_activity(config.RECENT_ACTIVITY_LIMIT)
    if recent:
        activity_table(recent)
    else:
        st.info("No activity recorded yet.", icon=ui.ALERT_ICONS["info"])

    if can("load_demo_data"):
        section("Demo data")
        ui.info_panel("Owner only",
                      "Generates a .txt, a .csv and a .png chart in code, uploads them into different "
                      "tiers through the normal upload function and creates one backup.")
        if st.button("Load demo data", type="primary", icon=":material/dataset:"):
            ok, created = attempt(demo_data.load_demo_data, current_user())
            if ok:
                flash("success", "Demo data loaded: " + ", ".join(created) + " + 1 backup.")
            st.rerun()


# ---------------------------------------------------------------------------
# File Manager
# ---------------------------------------------------------------------------
def files_table(files: list[dict]) -> None:
    rows = []
    for f in files:
        _, reason = storage.get_availability(f)
        rows.append({
            "ID": f["id"], "File name": f["original_name"], "Size": format_size(f["size_bytes"]),
            "Tier": [f["tier"]], "Redundancy": [f["redundancy"]],
            "Uploaded": pd.to_datetime(f["upload_date"]), "Tier changed": pd.to_datetime(f["tier_changed_at"]),
            "Status": [file_status(f)], "Availability": reason,
        })
    ui.table(pd.DataFrame(rows), {
        "ID": st.column_config.NumberColumn("ID", format="%d", width="small"),
        "Size": st.column_config.TextColumn("Size", width="small"),
        "Tier": ui.pill_column("Tier", ui.TIER_COLOURS),
        "Redundancy": ui.pill_column("Redundancy", ui.REDUNDANCY_COLOURS),
        "Uploaded": DATETIME("Uploaded", format=DATE_FORMAT),
        "Tier changed": DATETIME("Tier changed", format=DATE_FORMAT),
        "Status": ui.pill_column("Status", STATUS_COLOURS),
    })


def download_button(file_record: dict, key_prefix: str) -> None:
    """Show a working download button, or the reason the file is unavailable."""
    try:
        data, source = storage.read_file_for_download(file_record)
    except StorageError as exc:
        st.button("Unavailable", key=f"{key_prefix}_na_{file_record['id']}", icon=":material/block:",
                  disabled=True, help=str(exc), width="stretch")
        return
    st.download_button(
        "Download" + (" (secondary)" if source == "secondary" else ""),
        data=data, file_name=file_record["original_name"],
        mime=guess_mime(file_record["original_name"]),
        key=f"{key_prefix}_dl_{file_record['id']}",
        on_click=storage.log_download,
        args=(current_user(), file_record["original_name"], source),
        icon=":material/download:", width="stretch",
    )


def file_manager_page() -> None:
    ui.page_header("File Manager", "Upload, download and delete blobs in the simulated storage account")
    show_flash()

    # ---- Upload -----------------------------------------------------------
    section("Upload a file")
    if can("upload"):
        with st.form("upload_form", clear_on_submit=True):
            uploaded = st.file_uploader("Choose a file")
            col1, col2 = st.columns(2)
            tier = col1.selectbox("Access tier", config.UPLOAD_TIERS,
                                  help="Archive is not allowed at upload. Move a file to Archive later.")
            redundancy = col2.radio("Redundancy", list(config.REDUNDANCY.keys()), horizontal=True,
                                    format_func=lambda r: f"{r} - {config.REDUNDANCY[r]['name']}")
            submit = st.form_submit_button("Upload", type="primary", icon=":material/upload:")
        if submit:
            if uploaded is None:
                st.warning("Please choose a file first.", icon=ui.ALERT_ICONS["warning"])
            else:
                ok, _ = attempt(storage.upload_file, uploaded.getvalue(), uploaded.name,
                                tier, redundancy, current_user())
                if ok:
                    flash("success", f"'{uploaded.name}' uploaded to the {tier} tier with {redundancy}.")
                st.rerun()
        st.caption(f"Quota: {format_size(database.get_total_size())} used of "
                   f"{format_size(config.STORAGE_QUOTA_BYTES)}.")
    else:
        no_permission("upload files")

    # ---- File list ---------------------------------------------------------
    section("Files")
    files = database.get_all_files()
    if not files:
        st.info("No files stored yet.", icon=ui.ALERT_ICONS["info"])
        return
    files_table(files)

    section("Actions")
    widths = [3.2, 1.6, 1, 1.5, 1.2]
    header = st.columns(widths)
    for col, text in zip(header, ["File", "Tier / redundancy", "Size", "Download", "Delete"]):
        col.markdown(f"<div class='list-head'>{text}</div>", unsafe_allow_html=True)

    for f in files:
        cols = st.columns(widths, vertical_alignment="center")
        cols[0].markdown(f"<div class='row-title'>{f['original_name']}</div>"
                         f"<div class='row-meta'>ID {f['id']} &middot; uploaded {f['upload_date']}</div>",
                         unsafe_allow_html=True)
        cols[1].markdown(ui.badge(f["tier"]) + ui.badge(f["redundancy"]), unsafe_allow_html=True)
        cols[2].markdown(f"<div class='row-meta'>{format_size(f['size_bytes'])}</div>", unsafe_allow_html=True)
        with cols[3]:
            download_button(f, "fm")
        with cols[4]:
            if can("delete"):
                if st.button("Delete", key=f"del_{f['id']}", icon=":material/delete:", width="stretch"):
                    st.session_state["pending_delete"] = f["id"]
                    st.rerun()
            else:
                st.button("Delete", key=f"del_{f['id']}", icon=":material/lock:", disabled=True,
                          help="Your role cannot delete files.", width="stretch")

        # Confirmation step shown directly under the chosen file.
        if st.session_state.get("pending_delete") == f["id"]:
            remaining, charge = storage.early_deletion_info(f)
            with st.container(border=True):
                st.warning(f"Delete **{f['original_name']}** permanently? "
                           f"{'Its GRS copy in the secondary region will also be removed. ' if f['redundancy'] == 'GRS' else ''}"
                           "Backups of this file are kept.", icon=ui.ALERT_ICONS["warning"])
                if remaining > 0:
                    st.error(f"Early deletion: the {f['tier']} tier has a "
                             f"{config.TIERS[f['tier']]['min_days']}-day minimum and "
                             f"{remaining:.1f} days remain. Simulated charge: **{format_usd(charge)}**.",
                             icon=ui.ALERT_ICONS["error"])
                yes, no, _ = st.columns([1.3, 1, 4])
                if yes.button("Confirm delete", key=f"confirm_del_{f['id']}", icon=":material/delete_forever:"):
                    st.session_state.pop("pending_delete", None)
                    ok, charged = attempt(storage.delete_file, f["id"], current_user())
                    if ok:
                        flash("success", f"'{f['original_name']}' was deleted.")
                        charge_message(charged, f["original_name"], f["tier"])
                    st.rerun()
                if no.button("Cancel", key=f"cancel_del_{f['id']}"):
                    st.session_state.pop("pending_delete", None)
                    st.rerun()


# ---------------------------------------------------------------------------
# Storage Tiers
# ---------------------------------------------------------------------------
@st.fragment(run_every=3)
def rehydration_monitor() -> None:
    """Auto-refreshes every 3 s while files are rehydrating."""
    completed = storage.process_rehydrations()
    if completed:
        flash("success", "Rehydration completed: " + ", ".join(completed) + ". The file is online again.")
        st.rerun()                              # refresh the whole page
    for f in database.get_rehydrating_files():
        left = storage.rehydration_seconds_left(f)
        done = 1 - left / config.REHYDRATION_SECONDS
        st.progress(max(0.0, min(done, 1.0)),
                    text=f"{f['original_name']}: Archive to {f['rehydrate_target']}, about {left} s left")


def storage_tiers_page() -> None:
    ui.page_header("Storage Tiers", "Hot, Cool, Cold and Archive access tiers with early-deletion rules")
    show_flash()
    ui.info_panel("Simulation only",
                  "Tier changes here only update the database. No data is migrated between real cloud "
                  "storage systems. Prices are <b>illustrative, not official Azure prices</b>.", note=True)

    ui.table(pd.DataFrame([
        {"Tier": [name], "Price per GB/month": t["price_per_gb_month"],
         "Daily price per GB": t["price_per_gb_month"] / config.DAYS_PER_MONTH,
         "Minimum storage period": t["min_days"],
         "Access": ["Online" if t["online"] else "Offline"], "Best for": t["use"]}
        for name, t in config.TIERS.items()
    ]), {
        "Tier": ui.pill_column("Tier", ui.TIER_COLOURS),
        "Price per GB/month": st.column_config.NumberColumn(format="$%.4f"),
        "Daily price per GB": st.column_config.NumberColumn(format="$%.6f"),
        "Minimum storage period": st.column_config.NumberColumn(format="%d days"),
        "Access": ui.pill_column("Access", STATUS_COLOURS),
        "Best for": st.column_config.TextColumn(width="large"),
    })
    st.caption("Early-deletion charge = remaining days of the minimum period x the tier's daily price "
               "x size in GB (x 2 for GRS).")

    files = database.get_all_files()
    if not files:
        st.info("No files yet. Upload a file in the File Manager first.", icon=ui.ALERT_ICONS["info"])
        return

    # ---- Change tier --------------------------------------------------------
    section("Change a file's tier")
    if can("change_tier"):
        movable = [f for f in files if f["tier"] != "Archive" and f["rehydration_status"] != "Rehydrating"]
        if not movable:
            st.info("All files are in Archive. Use rehydration below.", icon=ui.ALERT_ICONS["info"])
        else:
            by_id = {f["id"]: f for f in movable}
            col1, col2 = st.columns(2)
            file_id = col1.selectbox("File", list(by_id.keys()),
                                     format_func=lambda i: f"#{i} {by_id[i]['original_name']} ({by_id[i]['tier']})")
            chosen = by_id[file_id]
            new_tier = col2.selectbox("New tier", [t for t in config.TIERS if t != chosen["tier"]])

            remaining, charge = storage.early_deletion_info(chosen)
            days_in = storage.days_in_current_tier(chosen)
            if remaining > 0:
                st.warning(f"**Early deletion warning:** '{chosen['original_name']}' has been in "
                           f"{chosen['tier']} for {days_in:.2f} days. The minimum is "
                           f"{config.TIERS[chosen['tier']]['min_days']} days, so {remaining:.1f} days "
                           f"remain. Simulated early-deletion charge: **{format_usd(charge)}**.",
                           icon=ui.ALERT_ICONS["warning"])
            else:
                st.success(f"No early-deletion charge: the {chosen['tier']} tier's minimum period is satisfied.",
                           icon=ui.ALERT_ICONS["success"])
            if new_tier == "Archive":
                st.warning("Archive is **offline**: the file cannot be downloaded until it is rehydrated.",
                           icon=":material/inventory_2:")

            if st.button("Apply tier change", type="primary", icon=":material/swap_vert:"):
                ok, charged = attempt(storage.change_tier, file_id, new_tier, current_user())
                if ok:
                    flash("success", f"'{chosen['original_name']}' moved from {chosen['tier']} to {new_tier}.")
                    charge_message(charged, chosen["original_name"], chosen["tier"])
                st.rerun()
    else:
        no_permission("change storage tiers")

    # ---- Archive & rehydration ---------------------------------------------
    section("Archive tier and rehydration")
    ui.info_panel("About rehydration",
                  "In real Azure, rehydrating from Archive can take <b>up to 15 hours</b> (standard priority). "
                  f"Here it is simulated with a {config.REHYDRATION_SECONDS}-second timer "
                  "(REHYDRATION_SECONDS in config.py).")
    archived = [f for f in files if f["tier"] == "Archive"]
    if not archived:
        st.info("No files in the Archive tier.", icon=ui.ALERT_ICONS["info"])
        return

    if any(f["rehydration_status"] == "Rehydrating" for f in archived):
        rehydration_monitor()

    for f in archived:
        with st.container(border=True):
            cols = st.columns([3, 1.3, 1.3], vertical_alignment="center")
            rehydrating = f["rehydration_status"] == "Rehydrating"
            status = (ui.badge("Rehydrating") + f"<span class='row-meta'>to {f['rehydrate_target']}</span>"
                      if rehydrating else ui.badge("Offline"))
            cols[0].markdown(f"<div class='row-title'>{f['original_name']}</div>"
                             f"<div class='row-meta'>ID {f['id']} &middot; {format_size(f['size_bytes'])}</div>"
                             f"<div style='margin-top:6px'>{ui.badge('Archive')}{status}</div>",
                             unsafe_allow_html=True)
            if rehydrating:
                if cols[1].button("Refresh status", key=f"refresh_{f['id']}", icon=":material/refresh:"):
                    st.rerun()
                continue
            if not can("rehydrate"):
                cols[1].caption("Your role cannot rehydrate.")
                continue
            remaining, charge = storage.early_deletion_info(f)
            if remaining > 0:
                cols[0].caption(f"Leaving Archive now incurs a simulated early-deletion charge of {format_usd(charge)} "
                                f"({remaining:.1f} days left of 180).")
            for col, target in zip(cols[1:], config.REHYDRATE_TARGETS):
                if col.button(f"Rehydrate to {target}", key=f"rh_{target}_{f['id']}",
                              icon=":material/autorenew:", width="stretch"):
                    ok, charged = attempt(storage.start_rehydration, f["id"], target, current_user())
                    if ok:
                        flash("info", f"Rehydration of '{f['original_name']}' to {target} started. "
                                      f"It completes in about {config.REHYDRATION_SECONDS} seconds.")
                        charge_message(charged, f["original_name"], "Archive")
                    st.rerun()


# ---------------------------------------------------------------------------
# Redundancy
# ---------------------------------------------------------------------------
def redundancy_page() -> None:
    ui.page_header("Redundancy", "LRS vs GRS and a simulated primary region outage")
    show_flash()

    ui.table(pd.DataFrame([
        {"Option": "LRS - Locally Redundant", "Copies": "3 copies in ONE datacenter",
         "Protects against": "Disk / server failure", "In this simulator": "data/storage/ only"},
        {"Option": "ZRS - Zone Redundant", "Copies": "3 copies across 3 availability zones in one region",
         "Protects against": "Whole datacenter (zone) failure", "In this simulator": "Explained only"},
        {"Option": "GRS - Geo-Redundant", "Copies": "LRS in primary + LRS in the paired secondary region",
         "Protects against": "Whole region outage", "In this simulator": "data/storage/ + data/secondary_region/"},
        {"Option": "GZRS - Geo-Zone Redundant", "Copies": "ZRS in primary + LRS in the paired secondary region",
         "Protects against": "Zone AND region failures", "In this simulator": "Explained only"},
    ]))
    ui.info_panel("Region pairs",
                  "Azure pairs regions (for example Central India and South India) so geo-replicated data "
                  "has a home hundreds of kilometres away. GRS costs roughly 2x because two copies are stored.")

    outage = storage.is_outage_active()
    c1, c2 = st.columns(2)
    c1.metric(config.PRIMARY_REGION_NAME, "Outage" if outage else "Online")
    c2.metric(config.SECONDARY_REGION_NAME, "Online")

    if can("simulate_outage"):
        if outage:
            if st.button("Restore primary region", type="primary", icon=":material/power:"):
                ok, _ = attempt(storage.set_outage, False, current_user())
                if ok:
                    flash("success", "Primary region restored. All online files are available again.")
                st.rerun()
        else:
            if st.button("Simulate primary region outage", type="primary", icon=":material/power_off:"):
                ok, _ = attempt(storage.set_outage, True, current_user())
                if ok:
                    flash("warning", "Primary region is DOWN. GRS files are served from the secondary "
                                     "region; LRS files are unavailable. Uploads and other writes are paused.")
                st.rerun()
    else:
        no_permission("simulate a region outage")

    if outage:
        st.error("Outage in progress: only GRS files can be read (from the secondary region).",
                 icon=":material/cloud_off:")

    files = database.get_all_files()
    section("File availability")
    if not files:
        st.info("No files yet.", icon=ui.ALERT_ICONS["info"])
        return
    widths = [3, 1.2, 3, 1.7]
    header = st.columns(widths)
    for col, text in zip(header, ["File", "Redundancy", "Availability", "Download"]):
        col.markdown(f"<div class='list-head'>{text}</div>", unsafe_allow_html=True)
    for f in files:
        available, reason = storage.get_availability(f)
        cols = st.columns(widths, vertical_alignment="center")
        cols[0].markdown(f"<div class='row-title'>{f['original_name']}</div>"
                         f"<div class='row-meta'>ID {f['id']}</div>", unsafe_allow_html=True)
        cols[1].markdown(ui.badge(f["redundancy"]), unsafe_allow_html=True)
        cols[2].markdown(ui.badge("Online" if available else "Unavailable")
                         + f"<span class='row-meta'>{reason}</span>", unsafe_allow_html=True)
        with cols[3]:
            download_button(f, "red")


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
def backups_page() -> None:
    ui.page_header("Backups", "Create backups, download them and restore files")
    show_flash()
    user = current_user()

    files = database.get_all_files()
    section("Create a backup")
    if not can("backup"):
        no_permission("create backups")
    elif not files:
        st.info("No files to back up yet.", icon=ui.ALERT_ICONS["info"])
    else:
        by_id = {f["id"]: f for f in files}
        file_id = st.selectbox("File to back up", list(by_id.keys()),
                               format_func=lambda i: f"#{i} {by_id[i]['original_name']} ({by_id[i]['tier']})")
        if by_id[file_id]["tier"] == "Archive":
            st.warning("Archive files are offline and cannot be read for a backup. Rehydrate first.",
                       icon=ui.ALERT_ICONS["warning"])
        if st.button("Create backup", type="primary", icon=":material/backup:"):
            ok, backup_id = attempt(backup.create_backup, file_id, user)
            if ok:
                flash("success", f"Backup #{backup_id} of '{by_id[file_id]['original_name']}' created.")
            st.rerun()

    section("Backups")
    backups = database.get_all_backups()
    if not backups:
        st.info("No backups yet.", icon=ui.ALERT_ICONS["info"])
        return

    ui.table(pd.DataFrame([{
        "Backup ID": b["id"], "Original file": b["original_name"],
        "Original file ID": b["file_id"],
        "Original status": ["Exists" if backup.original_still_exists(b) else "Deleted"],
        "Backup file": ["Present" if backup.backup_file_exists(b) else "Missing"],
        "Size": format_size(b["size_bytes"]), "Created": pd.to_datetime(b["created_at"]),
        "Created by": b["created_by"], "Stored as": b["backup_path"],
    } for b in backups]), {
        "Backup ID": st.column_config.NumberColumn(format="%d", width="small"),
        "Original file ID": st.column_config.NumberColumn(format="%d", width="small"),
        "Original status": ui.pill_column("Original status", YES_NO_COLOURS),
        "Backup file": ui.pill_column("Backup file", YES_NO_COLOURS),
        "Created": DATETIME("Created", format=DATE_FORMAT),
    })

    widths = [3.2, 1.5, 1.5]
    header = st.columns(widths)
    for col, text in zip(header, ["Backup", "Download", "Restore"]):
        col.markdown(f"<div class='list-head'>{text}</div>", unsafe_allow_html=True)

    for b in backups:
        exists = backup.original_still_exists(b)
        cols = st.columns(widths, vertical_alignment="center")
        cols[0].markdown(f"<div class='row-title'>#{b['id']} {b['original_name']}</div>"
                         f"<div class='row-meta'>{b['created_at']} &middot; "
                         f"{ui.badge('Original exists', 'online') if exists else ui.badge('Original deleted', 'neutral')}"
                         f"</div>", unsafe_allow_html=True)
        with cols[1]:
            try:
                _, data = backup.read_backup(b["id"])
                st.download_button("Download", data=data, file_name=b["original_name"],
                                   mime=guess_mime(b["original_name"]), key=f"bk_dl_{b['id']}",
                                   on_click=database.log_activity,
                                   args=(user["username"], user["role"], "Backup downloaded",
                                         b["original_name"], f"Backup #{b['id']}"),
                                   icon=":material/download:", width="stretch")
            except StorageError as exc:
                st.button("File missing", key=f"bk_na_{b['id']}", disabled=True, icon=":material/error:",
                          help=str(exc), width="stretch")
        with cols[2]:
            if can("restore"):
                if st.button("Restore", key=f"bk_rs_{b['id']}", icon=":material/restore:", width="stretch"):
                    st.session_state["pending_restore"] = b["id"]
                    st.rerun()
            else:
                st.button("Restore", key=f"bk_rs_{b['id']}", disabled=True, icon=":material/lock:",
                          help="Your role cannot restore backups.", width="stretch")

        if st.session_state.get("pending_restore") == b["id"]:
            with st.container(border=True):
                if exists:
                    st.warning(f"Restore backup #{b['id']}? The current content of "
                               f"**{b['original_name']}** (file #{b['file_id']}) will be **overwritten**.",
                               icon=ui.ALERT_ICONS["warning"])
                    confirm_key = f"danger_restore_{b['id']}"      # destructive: styled in danger colour
                else:
                    st.info(f"The original **{b['original_name']}** was deleted. Restoring will "
                            "re-create it as a **new file in the Hot tier** (LRS).", icon=ui.ALERT_ICONS["info"])
                    confirm_key = f"bk_yes_{b['id']}"
                yes, no, _ = st.columns([1.3, 1, 4])
                if yes.button("Confirm restore", key=confirm_key, type="primary", icon=":material/restore:"):
                    st.session_state.pop("pending_restore", None)
                    ok, message = attempt(backup.restore_backup, b["id"], user)
                    if ok:
                        flash("success", message)
                    st.rerun()
                if no.button("Cancel", key=f"bk_no_{b['id']}"):
                    st.session_state.pop("pending_restore", None)
                    st.rerun()


# ---------------------------------------------------------------------------
# Cost Estimator
# ---------------------------------------------------------------------------
def cost_estimator_page() -> None:
    ui.page_header("Cost Estimator", "Illustrative monthly and yearly storage costs (Azure Cost Management)")
    show_flash()
    ui.info_panel("Illustrative pricing",
                  "Prices are <b>illustrative</b>, not official Azure prices. GRS is simulated as "
                  "<b>2x the storage cost</b> because two copies (primary and secondary region) are stored.",
                  note=True)

    section("Current files")
    summary = pd.DataFrame(storage.tier_summary())
    summary["Size"] = summary["Bytes"].apply(format_size)
    summary["Yearly cost ($)"] = summary["Monthly cost ($)"] * 12
    current = summary[["Tier", "Files", "Size", "Monthly cost ($)", "Yearly cost ($)"]].copy()
    total = {"Tier": "Total", "Files": int(summary["Files"].sum()),
             "Size": format_size(summary["Bytes"].sum()),
             "Monthly cost ($)": summary["Monthly cost ($)"].sum(),
             "Yearly cost ($)": summary["Yearly cost ($)"].sum()}
    current = pd.concat([current, pd.DataFrame([total])], ignore_index=True)
    current["Tier"] = ui.as_pills(current["Tier"])
    ui.table(current, {
        "Tier": ui.pill_column("Tier", {**ui.TIER_COLOURS, "Total": "#1B2333"}),
        "Monthly cost ($)": st.column_config.NumberColumn("Monthly cost", format="$%.10f"),
        "Yearly cost ($)": st.column_config.NumberColumn("Yearly cost", format="$%.10f"),
    })

    section("What-if calculator")
    col1, col2 = st.columns(2)
    size_gb = col1.number_input("Data size (GB)", min_value=0.0, max_value=1_000_000.0,
                                value=100.0, step=10.0)
    redundancy = col2.radio("Redundancy", list(config.REDUNDANCY.keys()), horizontal=True, key="whatif_red")
    multiplier = config.REDUNDANCY[redundancy]["cost_multiplier"]

    rows = []
    for name, tier in config.TIERS.items():
        monthly = size_gb * tier["price_per_gb_month"] * multiplier
        rows.append({"Tier": [name], "Monthly cost ($)": round(monthly, 4),
                     "Yearly cost ($)": round(monthly * 12, 4)})
    ui.table(pd.DataFrame(rows), {
        "Tier": ui.pill_column("Tier", ui.TIER_COLOURS),
        "Monthly cost ($)": st.column_config.NumberColumn("Monthly cost", format="$%.2f"),
        "Yearly cost ($)": st.column_config.NumberColumn("Yearly cost", format="$%.2f"),
    })

    chart_rows = []
    for name, tier in config.TIERS.items():
        for red, info in config.REDUNDANCY.items():
            chart_rows.append({"Tier": name, "Redundancy": red,
                               "Monthly cost ($)": size_gb * tier["price_per_gb_month"] * info["cost_multiplier"]})
    fig = px.bar(pd.DataFrame(chart_rows), x="Tier", y="Monthly cost ($)", color="Redundancy",
                 barmode="group", text_auto=".2f",
                 color_discrete_map={"LRS": "#A6C8FF", "GRS": ui.PRIMARY},
                 title=f"Monthly cost of {size_gb:g} GB per tier (LRS vs GRS)")
    ui.plotly_chart(ui.style_chart(fig, height=380))


# ---------------------------------------------------------------------------
# Activity Log
# ---------------------------------------------------------------------------
def activity_log_page() -> None:
    ui.page_header("Activity Log", "Every action recorded, like Azure Monitor / Activity Log")
    show_flash()
    if not can("view_activity_log"):
        st.error(f"Access denied: only the **Owner** role can view the activity log. "
                 f"You are signed in as **{current_user()['role']}**.", icon=":material/lock:")
        database.log_activity(current_user()["username"], current_user()["role"], "Access denied",
                              details="Tried to open the Activity Log")
        return

    entries = database.get_activity()
    if not entries:
        st.info("The activity log is empty.", icon=ui.ALERT_ICONS["info"])
        return
    log = pd.DataFrame(entries)

    col1, col2, col3 = st.columns([1, 1.5, 1])
    users = col1.multiselect("User", sorted(log["username"].dropna().unique()))
    actions = col2.multiselect("Action", sorted(log["action"].dropna().unique()))
    search = col3.text_input("Filename contains")
    if users:
        log = log[log["username"].isin(users)]
    if actions:
        log = log[log["action"].isin(actions)]
    if search:
        log = log[log["filename"].fillna("").str.contains(search, case=False, regex=False)]

    st.caption(f"Showing {len(log)} of {len(entries)} entries")
    if log.empty:
        st.info("No entries match the filters.", icon=ui.ALERT_ICONS["info"])
    else:
        activity_table(log.to_dict("records"), height=480)
    st.download_button("Export as CSV", log.to_csv(index=False).encode("utf-8"),
                       file_name="activity_log.csv", mime="text/csv", icon=":material/download:")


# ---------------------------------------------------------------------------
# AZ-900 Concepts
# ---------------------------------------------------------------------------
def concepts_page() -> None:
    ui.page_header("AZ-900 Concepts", "How each feature maps to the Azure Fundamentals syllabus")
    show_flash()
    concepts = [
        ("Storage Tiers page", "Blob access tiers",
         "Hot, Cool, Cold and Archive trade storage price against access cost and speed."),
        ("Rehydrate buttons", "Archive rehydration",
         "Archive is offline; data must be rehydrated to Hot/Cool (up to 15 hours in Azure)."),
        ("Early-deletion warning", "Early deletion / minimum storage period",
         "Cool 30, Cold 90, Archive 180 days. Leaving early still charges the remaining days."),
        ("Redundancy page (LRS/GRS)", "Storage redundancy",
         "LRS keeps copies in one datacenter; GRS also copies to a secondary region. ZRS/GZRS use availability zones."),
        ("Outage simulation", "Region pairs and high availability",
         "Azure regions are paired; GRS data survives a primary region outage."),
        ("Login and roles", "Azure RBAC (role-based access control)",
         "Owner, Contributor and Reader are real Azure built-in roles with increasing restrictions."),
        ("Password hashing", "Identity and authentication (Microsoft Entra ID idea)",
         "Users prove identity before access; credentials are stored as salted hashes."),
        ("Backups page", "Backup and disaster recovery (Azure Backup)",
         "Point-in-time copies let you recover deleted or damaged data."),
        ("Cost Estimator / Dashboard", "Cost management and pricing factors",
         "Cost depends on size, tier and redundancy - similar to the Azure Pricing Calculator."),
        ("Storage quota", "Storage account limits / capacity planning",
         "An account has a capacity; uploads beyond the quota are rejected."),
        ("Activity Log page", "Azure Monitor / Activity Log",
         "Who did what and when - used for auditing and troubleshooting."),
        ("Whole app", "Shared responsibility model",
         "See the table below."),
    ]
    ui.table(pd.DataFrame(concepts, columns=["Feature in this app", "AZ-900 concept", "What it shows"]),
             {"What it shows": st.column_config.TextColumn(width="large")})

    section("Shared responsibility model")
    ui.info_panel("Who is responsible?",
                  "In every cloud model (IaaS, PaaS, SaaS) the <b>customer is always responsible</b> for their "
                  "<b>data</b>, <b>identities/accounts</b> and <b>access management</b>. The <b>cloud provider</b> "
                  "is responsible for physical datacenters, hardware, the network and the host infrastructure.")
    ui.table(pd.DataFrame([
        {"Responsibility": "Information and data (what you upload, backups)", "Who": ["Customer"],
         "In this app": "You choose tiers, redundancy and when to back up"},
        {"Responsibility": "Accounts and identities", "Who": ["Customer"],
         "In this app": "Demo users with hashed passwords"},
        {"Responsibility": "Access management (who can do what)", "Who": ["Customer"],
         "In this app": "Owner / Contributor / Reader roles"},
        {"Responsibility": "Physical datacenter, hosts and network", "Who": ["Microsoft (provider)"],
         "In this app": "Simulated by the local folders and region pair"},
        {"Responsibility": "Durability of replicas (LRS/GRS copies)", "Who": ["Microsoft (provider)"],
         "In this app": "Simulated by the secondary_region folder"},
    ]), {"Who": ui.pill_column("Who", {"Customer": ui.PRIMARY, "Microsoft (provider)": "#6929C4"})})


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        database.init_db()             # creates folders + tables on first run
        auth.seed_demo_users()         # creates the three demo users once
    except Exception as exc:
        st.error(f"Could not start the database at {config.DB_PATH}: {exc}", icon=ui.ALERT_ICONS["error"])
        st.stop()

    # Finish any simulated rehydration whose timer has run out.
    for name in storage.process_rehydrations():
        flash("success", f"Rehydration of '{name}' completed. The file is online again.")

    if "user" not in st.session_state:
        login_page()
        return

    page = sidebar()
    page_functions = {
        "Dashboard": dashboard_page,
        "File Manager": file_manager_page,
        "Storage Tiers": storage_tiers_page,
        "Redundancy": redundancy_page,
        "Backups": backups_page,
        "Cost Estimator": cost_estimator_page,
        "Activity Log": activity_log_page,
        "AZ-900 Concepts": concepts_page,
    }
    page_functions[page]()


main()
