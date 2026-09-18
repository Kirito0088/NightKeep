"""Notices file changes on the PDS server and which process caused them.

Public interface:
    events_since(t) -> [Event]
    is_alive()

Hides watchdog wiring, psutil polling, file-to-process attribution and the
append-only log.
"""
