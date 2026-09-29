#!/usr/bin/env python3
"""app/services/scheduler.py · 服务内置周期调度（DEV-0081，替代 crontab/launchd）

设计约束（owner 2026-09-26 定）：
  - 定时任务不依赖系统调度器——换机/TCC/双轨抢锁等系统性风险一并消除；
    服务起则调度在，服务停则调度停（与"服务是唯一运行面"的一键启动策略对齐）。
  - 每 3 小时一轮（BIDMASTER_SCHED_INTERVAL 秒可覆盖；0/负值 = 禁用），
    一轮 = 固定任务序列串行执行——轮内无并发，天然免跨任务锁。
  - 每任务独立子进程 + 独立超时；输出经 capture_output 回收后由本模块落盘到
    ~/.bidmaster/log/sched-<task>.log（每轮覆写，保留最近一轮——不再养 9.6MB 日志）。
  - 轮次汇总写 events（type=sched_round）并 SSE 广播——调度自身可观测，
    不复刻"cron_baw.sh exit 0 + || true 吞错"的绿色空转。
  - 手动触发（POST /api/v1/scheduler/run）与自动轮次共用一把进程内锁，防重入。

实现注记：子进程命令全部注册在模块级 TASK_RUNNERS（零参 lambda，参数列表为
静态字面量 + shell=False，无任何用户输入路径）——进程隔离与超时强杀能力保留。
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import config
from . import notify

REPO = config.REPO
VENV_PY = str(Path(sys.executable).resolve())  # 服务进程的解释器（start.sh 保证是 .venv）
_LOG_DIR = config.BIDMASTER_HOME / "log"
_SUBPROC_ENV = {**os.environ, "BIDMASTER_HOME": str(config.BIDMASTER_HOME)}
_LOG_TAIL_BYTES = 100 * 1024  # 单任务日志落盘上限（取尾部，防长输出膨胀）

# 轮次任务序列（顺序即执行顺序；每项 = (任务名, 超时秒, cadence 小时)。
# cadence=0 每轮都跑；>0 按 ~/_bidmaster/sched_state.json 的上次运行时间节流（B1.4：backup 每周）。
# 手动触发（POST /api/v1/scheduler/run）无视 cadence 强制全跑。
TASK_SEQUENCE = [
    ("capture", 900, 0),
    ("qualify", 300, 0),
    ("scout-validate", 300, 0),
    ("lead-status-check", 900, 0),
    ("ingest", 1800, 0),
    ("consistency", 300, 0),
    ("digest", 300, 0),
    ("backup", 300, 168),
]

# 任务执行器注册表（零参 lambda + 字面量参数列表 + shell=False；超时与 TASK_SEQUENCE 一致）
TASK_RUNNERS = {
    "capture": lambda: subprocess.run(
        ["bash", str(REPO / "scripts" / "lead_capture.sh")],
        shell=False, capture_output=True, cwd=str(REPO), timeout=900, env=_SUBPROC_ENV),
    "qualify": lambda: subprocess.run(
        [VENV_PY, str(REPO / "scripts" / "qualify_score.py")],
        shell=False, capture_output=True, cwd=str(REPO), timeout=300, env=_SUBPROC_ENV),
    "scout-validate": lambda: subprocess.run(
        [VENV_PY, str(REPO / "rules" / "validate_leads.py")],
        shell=False, capture_output=True, cwd=str(REPO), timeout=300, env=_SUBPROC_ENV),
    "lead-status-check": lambda: subprocess.run(
        [VENV_PY, str(REPO / "rules" / "lead_status_check.py"), "--limit", "50"],
        shell=False, capture_output=True, cwd=str(REPO), timeout=900, env=_SUBPROC_ENV),
    "ingest": lambda: subprocess.run(
        [VENV_PY, str(REPO / "rules" / "ingest.py"), "--all", "--types", "tender,lead-table"],
        shell=False, capture_output=True, cwd=str(REPO), timeout=1800, env=_SUBPROC_ENV),
    "consistency": lambda: subprocess.run(
        [VENV_PY, str(REPO / "rules" / "consistency.py")],
        shell=False, capture_output=True, cwd=str(REPO), timeout=300, env=_SUBPROC_ENV),
    "digest": lambda: subprocess.run(
        [VENV_PY, str(REPO / "scripts" / "digest_stats.py")],
        shell=False, capture_output=True, cwd=str(REPO), timeout=300, env=_SUBPROC_ENV),
    "backup": lambda: subprocess.run(
        [VENV_PY, str(REPO / "rules" / "backup.py")],
        shell=False, capture_output=True, cwd=str(REPO), timeout=300, env=_SUBPROC_ENV),
}

_STATE_FILE = config.BIDMASTER_HOME / "sched_state.json"  # {task: 上次执行 epoch 秒}

_round_lock = threading.Lock()   # 一轮一次（自动/手动共用）
_state_lock = threading.Lock()
_state = {
    "enabled": False,
    "interval_s": 0,
    "running": False,
    "last_round": None,           # {started_at, finished_at, tasks:[{name, rc, seconds, timed_out}]}
    "next_run_at": None,
}


def _write_task_log(name: str, rc, output: bytes) -> None:
    """单任务日志落盘（每轮覆写：头部元信息 + 输出尾部，防日志无界增长）。"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    tail = output[-_LOG_TAIL_BYTES:] if len(output) > _LOG_TAIL_BYTES else output
    header = (f"===== 调度轮次 {datetime.now().strftime('%F %T')} task={name} rc={rc} "
              f"(截取尾部 {len(tail)}/{len(output)} 字节) =====\n").encode("utf-8")
    (_LOG_DIR / f"sched-{name}.log").write_bytes(header + tail)


def _load_last_run() -> dict:
    """cadence 节流状态（跨重启持久）：{task: 上次执行 epoch 秒}。读失败按空处理（首跑必执行）。"""
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8")).get("last_run", {})
    except Exception:
        return {}


def _save_last_run(last_run: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps({"last_run": last_run}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def run_round(trigger: str = "auto") -> dict:
    """执行一轮（串行）。持有 _round_lock——自动轮次与手动触发互斥。

    cadence>0 的任务在自动轮次按上次运行时间节流（跳过记 skipped）；
    手动触发强制全跑。单任务失败/超时不中断轮次（rc 记入汇总，failed 列表驱动告警级别）。
    """
    with _round_lock:
        with _state_lock:
            if _state["running"]:
                return {"ok": False, "err": "上一轮仍在执行"}
            _state["running"] = True
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_ts = time.time()
        last_run = _load_last_run()
        results = []
        executed = []
        try:
            for name, _timeout_s, cadence_h in TASK_SEQUENCE:
                if cadence_h > 0 and trigger == "auto":
                    last_ts = float(last_run.get(name, 0) or 0)
                    if now_ts - last_ts < cadence_h * 3600:
                        results.append({"name": name, "skipped": True, "rc": None,
                                        "seconds": 0, "timed_out": False,
                                        "note": f"cadence {cadence_h}h 未到，跳过"})
                        continue
                entry = {"name": name, "rc": None, "seconds": 0, "timed_out": False}
                t0 = time.time()
                try:
                    runner = TASK_RUNNERS.get(name)
                    if runner is None:
                        entry["rc"] = 125
                        entry["error"] = f"未注册任务：{name}"
                        continue
                    proc = runner()
                    entry["rc"] = proc.returncode
                    _write_task_log(name, proc.returncode,
                                    (proc.stdout or b"") + (proc.stderr or b""))
                except subprocess.TimeoutExpired as e:
                    entry["timed_out"] = True
                    entry["rc"] = 124
                    _write_task_log(name, 124, (e.stdout or b"") + (e.stderr or b""))
                except Exception as e:  # 脚本缺失/权限等——调度不因单任务崩
                    entry["rc"] = 125
                    entry["error"] = str(e)[:200]
                entry["seconds"] = round(time.time() - t0, 1)
                results.append(entry)
                if entry.get("rc") is not None and entry["rc"] != 125:
                    executed.append(name)
        finally:
            finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            failed = [r for r in results if not r.get("skipped") and (r.get("rc") or 0) != 0]
            summary = {"ok": not failed, "trigger": trigger, "started_at": started,
                       "finished_at": finished, "tasks": results,
                       "failed": [r["name"] for r in failed]}
            with _state_lock:
                _state["last_round"] = summary
                _state["running"] = False
                if _state["enabled"]:
                    _state["next_run_at"] = datetime.fromtimestamp(
                        time.time() + _state["interval_s"]).strftime("%Y-%m-%d %H:%M:%S")
            if executed:
                last_run = _load_last_run()
                for name in executed:
                    last_run[name] = int(time.time())
                _save_last_run(last_run)
            # 可观测性：events 表 + log.jsonl + SSE 三通道（RETRO-001"可观测性优先"纪律）
            try:
                from ..store import app_db
                app_db.save_event({
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "type": "sched_round", "level": "warn" if failed else "info",
                    "module": "scheduler", "api": trigger,
                    "code": "SCHED_ROUND_" + ("FAILED" if failed else "OK"),
                    "msg": f"调度轮次完成（{trigger}）：{len(results)} 任务，失败 {len(failed)}",
                    "payload": json.dumps(summary, ensure_ascii=False)[:4000],
                })
            except Exception:
                pass
            notify.log_module("scheduler",
                              "⚙️ 调度轮次（" + trigger + "）完成："
                              + ", ".join(f"{r['name']}={r['rc']}" + ("⏱" if r["timed_out"] else "")
                                          for r in results),
                              "warn" if failed else "info")
            notify.sse.broadcast("sched_round", summary)
        return summary


def _loop(interval_s: int):
    # 首轮延迟 30s 启动（等服务 watcher/前端就绪），此后每 interval_s 一轮
    time.sleep(30)
    while True:
        try:
            if not _state["enabled"]:
                return
            run_round(trigger="auto")
        except Exception as e:
            notify.log_module("scheduler", f"调度循环异常: {e}", "warn")
        time.sleep(interval_s)


def start_scheduler() -> bool:
    """随服务启动（bootstrap start_watchers 段调用）。BIDMASTER_SCHED_INTERVAL=0 禁用。"""
    raw = os.environ.get("BIDMASTER_SCHED_INTERVAL", str(3 * 3600))
    try:
        interval_s = int(raw)
    except ValueError:
        interval_s = 3 * 3600
    if interval_s <= 0:
        with _state_lock:
            _state.update({"enabled": False, "interval_s": 0})
        notify.log_module("scheduler", "调度器未启用（BIDMASTER_SCHED_INTERVAL<=0）", "info")
        return False
    with _state_lock:
        _state.update({"enabled": True, "interval_s": interval_s,
                       "next_run_at": datetime.fromtimestamp(time.time() + 30).strftime(
                           "%Y-%m-%d %H:%M:%S")})
    threading.Thread(target=_loop, args=(interval_s,), daemon=True,
                     name="baw-scheduler").start()
    notify.log_module("scheduler",
                      f"⚙️ 服务内置调度器已启动：每 {interval_s // 60} 分钟一轮"
                      f"（{len(TASK_SEQUENCE)} 任务串行，日志 ~/.bidmaster/log/sched-*.log）", "info")
    return True


def run_status_check_now() -> dict:
    """单跑 lead-status-check 任务（供 lead.refresh_status 批量模式复用；同步阻塞，调用方自行放后台线程）。"""
    for name, _t, _c in TASK_SEQUENCE:
        if name == "lead-status-check":
            proc = TASK_RUNNERS[name]()
            _write_task_log(name, proc.returncode,
                            (proc.stdout or b"") + (proc.stderr or b""))
            return {"rc": proc.returncode}
    return {"rc": None, "err": "任务未注册"}


def status() -> dict:
    with _state_lock:
        s = dict(_state)
    last_run = _load_last_run()
    s["tasks"] = [{"name": n, "timeout_s": t, "cadence_h": c,
                   "last_run_at": (datetime.fromtimestamp(last_run[n]).strftime(
                       "%Y-%m-%d %H:%M:%S") if last_run.get(n) else None)}
                  for n, t, c in TASK_SEQUENCE]
    return s
