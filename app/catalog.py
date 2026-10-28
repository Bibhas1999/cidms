"""Built-in permissions and roles. Written to the database by app.seed and kept in step on every deploy."""

PLATFORM_PERMISSIONS = {
    "platform.clients.view": "See clients, their plans and usage",
    "platform.clients.manage": "Add clients, change their plan and status",
    "platform.subscriptions.manage": "Record subscription payments and renewals",
    "platform.staff.manage": "Add and remove platform staff",
    "platform.activity.view": "See the platform activity log",
    "platform.backups.manage": "Choose when the database is backed up, and back it up now",
}

CLIENT_PERMISSIONS = {
    "staff.manage": "Add staff, set their roles, deactivate them",
    "roles.manage": "Create and change the centre's own roles and what each can do",
    "settings.manage": "Change the centre's details, branding and numbering",
    "activity.view": "See the centre's activity log",
    "patients.manage": "Register and edit patients",
    "billing.create": "Create bills and take payments",
    "billing.edit": "Edit, hold or cancel bills",
    "billing.discount_over_limit": "Give discounts above the centre's limit",
    "payments.collect": "Collect dues and record refunds",
    "catalogue.manage": "Change departments, tests, prices and doctors",
    "worklist.update": "Mark scans done and upload images",
    "reports.deliver": "Mark test reports pending, ready or handed over to the patient",
    "reports.write": "Write and edit test reports",
    "reports.sign": "Sign and amend test reports",
    "appointments.manage": "Book appointments and run the OPD queue",
    "consultations.write": "Write OPD consultation notes",
    "business_reports.view": "See collection, dues and other business reports",
    "analytics.view": "See turnover, analytics and business figures",
    "account.manage_own": "Change their own sign-in email and password",
    "integrations.manage": "Create and revoke API keys for other systems (never financial data)",
    "backups.manage": "Back up the centre's data, download copies and restore one",
}

ALL_CLIENT = set(CLIENT_PERMISSIONS)
# Turnover and analytics, and changing your own sign-in details, are for the owner and the centre admin only
# (both hold ALL_CLIENT). Other staff see what's paid and what's due, never the turnover.

# code: (name, scope, description, permissions)
ROLES: dict[str, tuple[str, str, str, set[str]]] = {
    "platform_owner": ("Platform owner", "platform", "Everything on the platform", set(PLATFORM_PERMISSIONS)),
    "platform_support": ("Platform support", "platform", "View clients and help them", {"platform.clients.view", "platform.activity.view"}),
    "owner": ("Owner", "client", "Everything in the centre", ALL_CLIENT),
    # Restoring puts every record back to an earlier moment: the owner's call, not the day-to-day admin's.
    "admin": ("Centre admin", "client", "Runs the centre day to day", ALL_CLIENT - {"backups.manage"}),
    "receptionist": ("Receptionist", "client", "Patients, bills, payments and appointments",
                     {"patients.manage", "billing.create", "payments.collect", "appointments.manage", "reports.deliver"}),
    "technician": ("Technician", "client", "Worklist and images", {"worklist.update", "reports.deliver"}),
    "doctor": ("Doctor / radiologist", "client", "Reports and consultations",
               {"reports.write", "reports.sign", "consultations.write", "worklist.update", "reports.deliver"}),
    "accounts": ("Accounts", "client", "Business reports and dues", {"business_reports.view", "payments.collect"}),
    "developer": ("Developer", "client", "API keys and integrations, and the activity log; no billing or money",
                  {"integrations.manage", "activity.view"}),
}

# Only an owner can make someone an owner.
OWNER_ONLY_ROLES = {"owner"}
