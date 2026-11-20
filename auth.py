"""
auth.py
-------
Login, password hashing and role-based permissions (simulates Azure RBAC).

How passwords are protected:
* A random 16-byte SALT is generated for every user.
* The password + salt is run through PBKDF2-HMAC-SHA256 100,000 times.
* Only the resulting hash and the salt are stored - never the password itself.
* At login the same calculation is repeated and the hashes are compared using
  hmac.compare_digest (a constant-time comparison).

NOTE: this is educational authentication, not production-grade security.
"""

import hashlib
import hmac
import secrets

import config
import database


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Return (hash_hex, salt_hex). A new random salt is made if none is given."""
    if salt_hex is None:
        salt_hex = secrets.token_bytes(config.SALT_BYTES).hex()
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        config.PBKDF2_ITERATIONS,
    )
    return password_hash.hex(), salt_hex


def verify_password(password: str, stored_hash_hex: str, salt_hex: str) -> bool:
    """Hash the typed password with the stored salt and compare safely."""
    candidate_hash, _ = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate_hash, stored_hash_hex)


def seed_demo_users() -> None:
    """Create the three demo users on first run (skipped if they already exist)."""
    for user in config.DEMO_USERS:
        if database.get_user(user["username"]) is None:
            password_hash, salt = hash_password(user["password"])
            database.add_user(user["username"], password_hash, salt, user["role"])


def authenticate(username: str, password: str) -> dict | None:
    """Check a username/password. Returns {'username', 'role'} or None."""
    username = (username or "").strip().lower()
    record = database.get_user(username)
    if record and verify_password(password or "", record["password_hash"], record["salt"]):
        database.log_activity(username, record["role"], "Login", details="Successful login")
        return {"username": record["username"], "role": record["role"]}

    database.log_activity(username or "(blank)", "-", "Login failed",
                          details="Invalid username or password")
    return None


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------
def has_permission(user: dict | None, permission: str) -> bool:
    """True if the user's role includes the permission."""
    if not user:
        return False
    return permission in config.ROLE_PERMISSIONS.get(user["role"], set())


def require_permission(user: dict | None, permission: str) -> None:
    """
    Raise PermissionError if the user may not perform an action.
    The UI already hides forbidden buttons; this check is a second safety net
    inside the back-end functions (defence in depth).
    """
    if not has_permission(user, permission):
        role = user["role"] if user else "Anonymous"
        if user:
            database.log_activity(user["username"], role, "Access denied",
                                  details=f"Missing permission: {permission}")
        raise PermissionError(
            f"Access denied: the {role} role cannot perform '{permission.replace('_', ' ')}'."
        )
