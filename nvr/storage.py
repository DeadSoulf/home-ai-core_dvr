"""Read-only capacity statistics for the filesystem hosting NVR recordings."""
import os
from pathlib import Path


def capacity_snapshot(path):
    """Report filesystem usage, not just the sum of NVR archive files.

    f_bfree includes root-reserved blocks. f_bavail is the amount the
    unprivileged recorder can actually use and is displayed separately.
    """
    root = Path(path)
    stats = os.statvfs(root)
    block_size = stats.f_frsize or stats.f_bsize
    total = stats.f_blocks * block_size
    free = stats.f_bfree * block_size
    available = stats.f_bavail * block_size
    if not (0 <= available <= free <= total):
        raise OSError("inconsistent filesystem capacity")
    return {
        "ok": True,
        "path": str(root),
        "total_bytes": total,
        "used_bytes": total - free,
        "free_bytes": free,
        "available_bytes": available,
        "used_percent": round((total - free) * 100 / total, 2) if total else 0,
    }
