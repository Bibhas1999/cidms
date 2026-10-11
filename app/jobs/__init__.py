"""Background job handlers. Every module here is imported by app.core.jobs.load_job_modules(), so a new job kind
is a new module with an @job("kind") function (see app/core/jobs.py)."""
