"""How permissions are shown when building roles: grouped by area of work, each with a short label.

The codes and their one-line descriptions live in app/catalog.py (written to the database by app.seed). This
adds the words people see in Settings → Roles & permissions. A permission added to the catalog but not listed
here still appears, under "Other", with its code turned into a label, so a new permission is never hidden.
"""

from app.catalog import CLIENT_PERMISSIONS, PLATFORM_PERMISSIONS

# key: (group label, what the area covers, {permission code: label})
GROUPS: dict[str, tuple[str, str, dict[str, str]]] = {
    "front_desk": ("Front desk & billing", "Bills, discounts and appointments at the counter", {
        "billing.create": "Create bills",
        "billing.edit": "Edit, hold or cancel bills",
        "billing.discount_over_limit": "Discounts above the limit",
        "appointments.manage": "Appointments and OPD queue",
    }),
    "payments": ("Payments", "Money coming in and going back", {
        "payments.collect": "Collect dues and refunds",
    }),
    "lab": ("Lab & worklist", "The day's scans and tests", {
        "worklist.update": "Update the worklist",
    }),
    "reports": ("Reports", "Writing, signing and consultation notes", {
        "reports.write": "Write reports",
        "reports.sign": "Sign and amend reports",
        "consultations.write": "Consultation notes",
    }),
    "catalogue": ("Catalogue", "Departments, tests, prices and referring doctors", {
        "catalogue.manage": "Manage the catalogue",
    }),
    "patients": ("Patients", "Patient records", {
        "patients.manage": "Register and edit patients",
    }),
    "staff_settings": ("Staff & settings", "People, roles, the centre's settings and its activity log", {
        "staff.manage": "Manage staff",
        "roles.manage": "Manage roles & permissions",
        "settings.manage": "Centre settings",
        "activity.view": "Activity log",
        "account.manage_own": "Change own sign-in details",
    }),
    "business": ("Business & analytics", "Turnover, collections and dues", {
        "business_reports.view": "Business reports",
        "analytics.view": "Analytics and turnover",
    }),
    "integrations": ("Integrations", "Connections to other systems", {
        "integrations.manage": "API keys",
    }),
    "platform": ("Platform", "Running the Supreme DMS platform (platform staff only)", {
        "platform.clients.view": "See clients",
        "platform.clients.manage": "Manage clients",
        "platform.subscriptions.manage": "Subscriptions",
        "platform.staff.manage": "Platform staff",
        "platform.activity.view": "Platform activity log",
    }),
}


def _fallback_label(code: str) -> str:
    return code.replace(".", " · ").replace("_", " ").capitalize()


def label_of(code: str) -> str:
    for _, _, perms in GROUPS.values():
        if code in perms:
            return perms[code]
    return _fallback_label(code)


def grouped(scope: str) -> list[dict]:
    """The permissions of one scope ("client" or "platform"), grouped, in a stable order."""
    catalog = PLATFORM_PERMISSIONS if scope == "platform" else CLIENT_PERMISSIONS
    seen: set[str] = set()
    out: list[dict] = []
    for key, (label, description, perms) in GROUPS.items():
        items = [{"code": c, "label": lbl, "description": catalog[c]} for c, lbl in perms.items() if c in catalog]
        seen.update(i["code"] for i in items)
        if items:
            out.append({"key": key, "label": label, "description": description, "permissions": items})
    rest = [{"code": c, "label": _fallback_label(c), "description": d} for c, d in catalog.items() if c not in seen]
    if rest:
        out.append({"key": "other", "label": "Other", "description": "Other permissions", "permissions": rest})
    return out
