"""Operator scripts. Not part of the runtime ``app`` package.

Each module in here is a CLI invoked via ``python -m scripts.<name>``
from inside ``backend/``. These are deliberately separate from
``app.cli`` — those are production cron + runbook scripts that run
against the real database; the scripts here are dev / spike tooling
that operates on files (no DB) and is allowed to be chatty.
"""
