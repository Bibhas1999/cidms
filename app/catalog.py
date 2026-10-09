"""Built-in permissions and roles. Written to the database by app.seed and kept in step on every deploy."""

PLATFORM_PERMISSIONS = {
    "platform.clients.view": "See clients, their plans and usage",
    "platform.clients.manage": "Add clients, change their plan and status",
    "platform.subscriptions.manage": "Record subscription payments and renewals",
    "platform.staff.manage": "Add and remove platform staff",
    "platform.activity.view": "See the platform activity log",
}

CLIENT_PERMISSIONS = {
    "staff.manage": "Add staff, set their roles, deactivate them",
    "settings.manage": "Change the centre's details, branding and numbering",
    "activity.view": "See the centre's activity log",
    "patients.manage": "Register and edit patients",
    "billing.create": "Create bills and take payments",
    "billing.edit": "Edit, hold or cancel bills",
    "billing.discount_over_limit": "Give discounts above the centre's limit",
    "payments.collect": "Collect dues and record refunds",
    "catalogue.manage": "Change departments, tests, prices and doctors",
    "worklist.update": "Mark scans done and upload images",
    "reports.write": "Write and edit test reports",
    "reports.sign": "Sign and amend test reports",
    "appointments.manage": "Book appointments and run the OPD queue",
    "consultations.write": "Write OPD consultation notes",
    "business_reports.view": "See collection, dues and other business reports",
}

ALL_CLIENT = set(CLIENT_PERMISSIONS)

# code: (name, scope, description, permissions)
ROLES: dict[str, tuple[str, str, str, set[str]]] = {
    "platform_owner": ("Platform owner", "platform", "Everything on the platform", set(PLATFORM_PERMISSIONS)),
    "platform_support": ("Platform support", "platform", "View clients and help them", {"platform.clients.view", "platform.activity.view"}),
    "owner": ("Owner", "client", "Everything in the centre", ALL_CLIENT),
    "admin": ("Centre admin", "client", "Runs the centre day to day", ALL_CLIENT),
    "receptionist": ("Receptionist", "client", "Patients, bills, payments and appointments",
                     {"patients.manage", "billing.create", "payments.collect", "appointments.manage"}),
    "technician": ("Technician", "client", "Worklist and images", {"worklist.update"}),
    "doctor": ("Doctor / radiologist", "client", "Reports and consultations",
               {"reports.write", "reports.sign", "consultations.write", "worklist.update"}),
    "accounts": ("Accounts", "client", "Business reports and dues", {"business_reports.view", "payments.collect"}),
}

# Only an owner can make someone an owner.
OWNER_ONLY_ROLES = {"owner"}
