"""Genuine /proc-based resource measurements (no synthetic numbers)."""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, rest = line.split(":", 1)
            values[key] = int(rest.strip().split()[0])
    except (OSError, ValueError):
        pass
    return values


def _cpu_total() -> int:
    try:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        return sum(int(v) for v in fields)
    except (OSError, ValueError, IndexError):
        return 0


def _processes() -> dict[int, dict[str, Any]]:
    procs: dict[int, dict[str, Any]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            stat = (entry / "stat").read_text()
            # comm may contain spaces/parentheses; split around the last ')'
            close = stat.rfind(")")
            comm = stat[stat.find("(") + 1:close]
            rest = stat[close + 2:].split()
            utime, stime = int(rest[11]), int(rest[12])
            rss_pages = int((entry / "statm").read_text().split()[1])
            procs[pid] = {"comm": comm, "cpu_ticks": utime + stime,
                          "rss_mb": rss_pages * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024}
        except (OSError, ValueError, IndexError):
            continue
    return procs


def snapshot(interval: float = 3.0) -> dict[str, Any]:
    mem = _meminfo()
    total_mb = mem.get("MemTotal", 0) / 1024
    available_mb = mem.get("MemAvailable", 0) / 1024
    cpu1 = _cpu_total()
    procs1 = _processes()
    time.sleep(interval)
    cpu2 = _cpu_total()
    procs2 = _processes()
    delta_cpu = max(1, cpu2 - cpu1)
    cpu_count = os.cpu_count() or 1

    shell = None
    cpu_by_pid: dict[int, float] = {}
    for pid, info in procs2.items():
        before = procs1.get(pid, {}).get("cpu_ticks", info["cpu_ticks"])
        ticks = max(0, info["cpu_ticks"] - before)
        cpu_by_pid[pid] = 100.0 * ticks / delta_cpu * cpu_count
        if info["comm"] == "gnome-shell" and shell is None:
            shell = {"pid": pid, "rss_mb": round(info["rss_mb"], 1),
                     "cpu_pct": round(cpu_by_pid[pid], 1)}
    top = sorted(procs2.items(), key=lambda kv: kv[1]["rss_mb"], reverse=True)[:8]
    gjs_count = sum(1 for p in procs2.values() if p["comm"] == "gjs")
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ram_total_mb": round(total_mb),
        "ram_used_mb": round(total_mb - available_mb),
        "process_count": len(procs2),
        "gjs_processes": gjs_count,
        "gnome_shell": shell,
        "top_by_rss": [
            {"pid": pid, "comm": info["comm"], "rss_mb": round(info["rss_mb"], 1),
             "cpu_pct": round(cpu_by_pid.get(pid, 0.0), 1)}
            for pid, info in top
        ],
        "sample_seconds": interval,
    }


def disk_usage(paths: list[Path]) -> dict[str, int]:
    result: dict[str, int] = {}
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        total = 0
        if path.is_file():
            total = path.stat().st_size
        else:
            for root, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        total += os.lstat(os.path.join(root, name)).st_size
                    except OSError:
                        continue
        result[str(path)] = round(total / 1024 / 1024, 1)
    return result
