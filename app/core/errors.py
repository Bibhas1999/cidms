"""Domain errors raised by services. Routes never build HTTP errors themselves; the handlers in
app/main.py turn these into JSON with a message people can read and the request ID for support."""


class DomainError(Exception):
    status = 400

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


class Unauthorized(DomainError):
    status = 401


class Forbidden(DomainError):
    status = 403


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409


class Invalid(DomainError):
    """A business rule failed for a specific field (shown next to that field)."""
    status = 422


class Locked(DomainError):
    status = 423


class TooManyRequests(DomainError):
    status = 429
