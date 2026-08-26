# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_FILE = Path("output/scheduled_refresh_status.json")
LOG_DIR = Path("logs")
LOCK_FILE = LOG_DIR / "scheduled_refresh.lock"
CHECK_INTERVAL_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 60 * 45

SCHEDULED_JOBS = [
    {
        "time": "09:39",
        "name": "开盘计划刷新",
        "commands": [
            "market",
            "candidates",
            "tail",
            "plan",
            "holdings-refresh",
            "opening-levels",
            "holdings-signals",
            "sell",
            "model-predict",
            "probability-predict",
            "decision-fusion",
        ],
    },
    {
        "time": "14:00",
        "name": "午后动态刷新",
        "commands": [
            "market",
            "holdings-refresh",
            "opening-levels",
            "holdings-signals",
            "sell",
            "lunch",
            "model-predict",
            "probability-predict",
            "decision-fusion",
        ],
    },
    {
        "time": "14:30",
        "name": "尾盘前动态刷新",
        "commands": [
            "market",
            "holdings-refresh",
            "opening-levels",
            "holdings-signals",
            "sell",
            "lunch",
            "model-predict",
            "probability-predict",
            "decision-fusion",
        ],
    },
    {
        "time": "15:00",
        "name": "收盘复盘刷新",
        "commands": [
            "market",
            "holdings-refresh",
            "opening-levels",
            "holdings-signals",
            "sell",
            "lunch",
            "next-day",
            "dataset",
            "model-predict",
            "probability-predict",
            "decision-fusion",
            "daily-report",
        ],
    },
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def job_key(job: dict[str, Any]) -> str:
    return f"{job['time']}_{job['name']}"


def default_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "running": False,
        "last_started_at": "",
        "last_finished_at": "",
        "last_job": "",
        "last_success": None,
        "last_error": "",
        "last_runs": {},
        "history": [],
        "schedule": [
            {
                "time": job["time"],
                "name": job["name"],
                "commands": job["commands"],
            }
            for job in SCHEDULED_JOBS
        ],
    }


def read_state(path: Path = STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return default_state()

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_state()

    merged = default_state()
    merged.update(state)
    merged["last_runs"] = state.get("last_runs", {})
    merged["history"] = state.get("history", [])
    merged["schedule"] = default_state()["schedule"]
    return merged


def write_state(state: dict[str, Any], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def is_trading_weekday(now: datetime) -> bool:
    return now.weekday() < 5


def due_jobs(state: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    current = now or datetime.now()
    if not is_trading_weekday(current):
        return []

    current_hm = current.strftime("%H:%M")
    today = today_text(current)
    last_runs = state.get("last_runs", {})
    jobs = []

    for job in SCHEDULED_JOBS:
        if current_hm >= job["time"] and last_runs.get(job_key(job)) != today:
            jobs.append(job)

    return jobs


def append_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"scheduled_refresh_{today_text()}.log"
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


def run_main_command(command: str) -> dict[str, Any]:
    started = now_text()
    append_log(f"[{started}] start {command}")

    try:
        result = subprocess.run(
            [sys.executable, "main.py", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        finished = now_text()
        success = result.returncode == 0
        append_log(f"[{finished}] finish {command} success={success}")

        if result.stdout:
            append_log(result.stdout[-4000:])
        if result.stderr:
            append_log(result.stderr[-4000:])

        return {
            "command": command,
            "success": success,
            "returncode": result.returncode,
            "started_at": started,
            "finished_at": finished,
            "stdout_tail": (result.stdout or "")[-1000:],
            "stderr_tail": (result.stderr or "")[-1000:],
        }
    except Exception as exc:
        finished = now_text()
        append_log(f"[{finished}] fail {command}: {exc}")
        return {
            "command": command,
            "success": False,
            "returncode": -1,
            "started_at": started,
            "finished_at": finished,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }


def run_job(job: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    key = job_key(job)
    started = now_text()
    state.update({
        "running": True,
        "last_started_at": started,
        "last_finished_at": "",
        "last_job": job["name"],
        "last_success": None,
        "last_error": "",
    })
    write_state(state)
    append_log(f"[{started}] job start {key}")

    command_results = [run_main_command(command) for command in job["commands"]]
    success = all(result["success"] for result in command_results)
    error_commands = [
        result["command"]
        for result in command_results
        if not result["success"]
    ]
    finished = now_text()

    state["running"] = False
    state["last_finished_at"] = finished
    state["last_job"] = job["name"]
    state["last_success"] = success
    state["last_error"] = "；".join(error_commands)
    state.setdefault("last_runs", {})[key] = today_text()
    state.setdefault("history", []).insert(0, {
        "job_key": key,
        "name": job["name"],
        "scheduled_time": job["time"],
        "started_at": started,
        "finished_at": finished,
        "success": success,
        "failed_commands": error_commands,
    })
    state["history"] = state["history"][:20]
    write_state(state)
    append_log(f"[{finished}] job finish {key} success={success}")

    return state["history"][0]


def run_due_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    state = read_state()
    jobs = due_jobs(state, now)
    results = []

    for job in jobs:
        state = read_state()
        if state.get("running"):
            break
        results.append(run_job(job, state))

    return results


def daemon_loop() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            append_log(f"[{now_text()}] another scheduler is already running")
            return

        append_log(f"[{now_text()}] scheduled refresh daemon started")
        while True:
            run_due_jobs()
            time.sleep(CHECK_INTERVAL_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="后台定时刷新交易系统数据")
    parser.add_argument("--daemon", action="store_true", help="常驻后台，按固定时间自动刷新")
    parser.add_argument("--once", action="store_true", help="只检查并执行一次到期任务")
    parser.add_argument("--status", action="store_true", help="输出当前刷新状态")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.status:
        print(json.dumps(read_state(), ensure_ascii=False, indent=2))
        return 0

    if args.once:
        results = run_due_jobs()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if args.daemon:
        daemon_loop()
        return 0

    print(json.dumps(read_state(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
