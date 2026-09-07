# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared imports for calendar route tests."""


def import_calendar_routes():
    """Import the calendar routes module after test stubs are installed."""
    import routes.calendar_routes as cal

    return cal
