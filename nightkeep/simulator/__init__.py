"""The safe ransomware simulator and its decrypt script.

Refuses to run outside the demo folder, uses a known key, does not spread, and
only echoes recovery-killing command text. It never executes vssadmin, wbadmin
or bcdedit.
"""
