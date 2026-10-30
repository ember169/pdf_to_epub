"""Environment-driven settings, read at app creation time."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_mb: int = 100
    job_ttl_hours: float = 24.0
    max_concurrent_jobs: int = 2
    auth_token: str | None = None
    max_queued_jobs: int = 20
    job_timeout_s: float | None = 600.0
    job_max_mem_mb: int | None = 2048
    max_pages: int | None = 2000
    allowed_hosts: tuple[str, ...] = ()
    janitor_interval_s: float = 600.0
    desktop: bool = False  # set by the no-argument launch only
    idle_exit_min: float = 15.0  # desktop mode: exit after this many idle minutes (0 = never)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "./data")).resolve(),
            max_upload_mb=_int("MAX_UPLOAD_MB", 100),
            job_ttl_hours=_float("JOB_TTL_HOURS", 24.0),
            max_concurrent_jobs=_int("MAX_CONCURRENT_JOBS", 2),
            auth_token=os.environ.get("AUTH_TOKEN") or None,
            max_queued_jobs=_int("MAX_QUEUED_JOBS", 20),
            job_timeout_s=_float("JOB_TIMEOUT_S", 600.0) or None,
            job_max_mem_mb=_int("JOB_MAX_MEM_MB", 2048, 0) or None,
            max_pages=_int("MAX_PAGES", 2000, 0) or None,
            idle_exit_min=max(0.0, _float("IDLE_EXIT_MIN", 15.0)),
            allowed_hosts=tuple(h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()),
        )
