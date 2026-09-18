"""The separate machine that holds the backups. It always opens the connection.

Public interface:
    pull()
    snapshots()
    restore(snapshot_id) -> RestoreResult

Hides SMB read, content-addressed blobs, manifests, the hash chain, the health
check, clean points and verification. The PDS server never gets a path,
credential or address for the Vault.
"""
