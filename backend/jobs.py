"""SQLite-backed job queue for a single Uvicorn worker."""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
from math import isfinite
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
from threading import BoundedSemaphore
import time
from uuid import uuid4

SCRIPTS = Path(__file__).with_name("abaqus")
STA_ROW = re.compile(r"^\s*1\s+\d+\s+\d+(?:U)?\s+\d+\s+\d+\s+\d+\s+(\S+)\s+(\S+)", re.M)


class QueueFull(Exception):
    pass


class SolveFailed(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    results: Path
    abaqus: str | None
    workers: int
    queue_limit: int
    timeout_seconds: int
    cpus: int

    @classmethod
    def from_env(cls):
        configured = os.getenv("ABAQUS_PATH", "").strip()
        workers = max(1, min(4, int(os.getenv("ABAQUS_MAX_RUNNING", "1"))))
        launch = shutil.which(configured) if configured else None
        return cls(
            Path(os.getenv("ABAQUS_RESULTS_DIR", "results")).resolve(),
            str(Path(launch).resolve()) if launch else None,
            workers,
            max(workers, min(24, int(os.getenv("ABAQUS_QUEUE_LIMIT", "8")))),
            max(10, int(os.getenv("ABAQUS_TIMEOUT_SECONDS", "1800"))),
            max(1, min(16, int(os.getenv("ABAQUS_CPUS", "2")))),
        )


class Jobs:
    def __init__(self, settings):
        self.settings = settings
        self.db = settings.results / "jobs.sqlite3"
        self.slots = BoundedSemaphore(settings.workers)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.settings.results.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, progress INTEGER NOT NULL,
                    message TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    parameters TEXT NOT NULL, result TEXT
                )
            """)
            db.execute("""
                UPDATE jobs SET status='failed', message='服务重启，之前的任务已中断。', updated=?
                WHERE status IN ('queued', 'running')
            """, (time.time(),))

    def create(self, params):
        job_id = str(uuid4())
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= self.settings.queue_limit:
                raise QueueFull
            db.execute("INSERT INTO jobs VALUES (?, 'queued', 0, ?, ?, ?, ?, NULL)",
                       (job_id, "任务已排队。", now, now, json.dumps(params, allow_nan=False)))
        return job_id

    def recent(self, limit):
        with self.connect() as db:
            rows = db.execute("""
                SELECT id, status, progress, message, updated, parameters FROM jobs
                ORDER BY created DESC, id DESC LIMIT ?
            """, (limit,)).fetchall()
        jobs = []
        for row in rows:
            params = json.loads(row["parameters"])
            jobs.append({
                "job_id": row["id"], "status": row["status"], "progress": row["progress"],
                "message": row["message"], "updated_at": row["updated"],
                "bolt_count": params["n"], "pressure_mpa": params["pressure_mpa"],
            })
        return jobs

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def update(self, job_id, status, progress, message, result=None):
        with self.connect() as db:
            db.execute("""
                UPDATE jobs SET status=?, progress=max(progress, ?), message=?, updated=?, result=? WHERE id=?
            """, (status, progress, message, time.time(),
                  json.dumps(result, allow_nan=False) if result is not None else None, job_id))

    @staticmethod
    def solver_progress(folder):
        sta = folder / "clamp.sta"
        msg = folder / "clamp.msg"
        if sta.is_file():
            with sta.open("rb") as file:
                file.seek(max(0, sta.stat().st_size - 32768))
                tail = file.read().decode("ascii", "ignore")
            increments = []
            for _, step_time in STA_ROW.findall(tail):
                try:
                    value = float(step_time.replace("D", "E"))
                    if isfinite(value) and 0 <= value <= 1.000001:
                        increments.append(value)
                except ValueError:
                    continue
            if increments:
                return 25 + int(50 * min(1, max(increments)))
        return 25 if msg.is_file() else 12

    @staticmethod
    def stop(process):
        if os.name == "nt":
            # Limit termination to the process tree started for this job.
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)

    def invoke(self, folder, job_id, args, log_name, deadline, report_solver=False):
        if time.monotonic() > deadline:
            raise SolveFailed("作业超过配置的总时限。")
        switches = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        # Only the configured executable and fixed internal script names are passed to the launcher.
        with (folder / log_name).open("wb") as log:
            process = subprocess.Popen([self.settings.abaqus, *args], cwd=folder,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, **switches)
            last_progress = 0
            try:
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise SolveFailed("作业超过配置的总时限。")
                    if report_solver:
                        progress = self.solver_progress(folder)
                        if progress > last_progress:
                            self.update(job_id, "running", progress,
                                        "Abaqus/Standard 求解中。" if progress >= 25 else "正在建立模型和网格。")
                            last_progress = progress
                    time.sleep(0.35)
            finally:
                if process.poll() is None:
                    self.stop(process)
            if process.returncode != 0:
                raise SolveFailed(f"Abaqus 阶段异常退出，请查看本机 {log_name}。")

    @staticmethod
    def clean_failed(folder):
        for name in ("clamp.lck", "clamp.odb", "s33.png", "result.json"):
            (folder / name).unlink(missing_ok=True)
        Jobs.clean_scratch(folder)

    @staticmethod
    def clean_scratch(folder):
        scratch = folder / "scratch"
        if scratch.is_dir() and not scratch.is_symlink() and scratch.resolve().parent == folder.resolve():
            shutil.rmtree(scratch, ignore_errors=True)

    def run(self, job_id):
        with self.slots:
            entry = self.get(job_id)
            if not entry or entry["status"] != "queued":
                return
            folder = self.settings.results / job_id
            try:
                self.update(job_id, "running", 5, "正在准备 Abaqus 作业目录。")
                folder.mkdir(exist_ok=False)
                for name in ("build_model.py", "extract_s33.py", "render_s33.py"):
                    shutil.copyfile(SCRIPTS / name, folder / name)
                input_data = {"parameters": json.loads(entry["parameters"]), "cpus": self.settings.cpus}
                (folder / "input.json").write_text(json.dumps(input_data, allow_nan=False), encoding="utf-8")
                deadline = time.monotonic() + self.settings.timeout_seconds
                self.invoke(folder, job_id, ["cae", "noGUI=build_model.py"], "solve.log", deadline, report_solver=True)
                if not (folder / "clamp.odb").is_file() or not (folder / "clamp.odb").stat().st_size:
                    raise SolveFailed("求解阶段没有生成 ODB，请查看本机 solve.log。")
                self.update(job_id, "running", 80, "正在读取 ODB 中的 S33 场输出。")
                self.invoke(folder, job_id, ["python", "extract_s33.py"], "extract.log", deadline)
                self.update(job_id, "running", 90, "正在用 Abaqus 生成 75% 节点平均云图。")
                self.invoke(folder, job_id, ["viewer", "noGUI=render_s33.py"], "render.log", deadline)
                result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
                png = folder / "s33.png"
                with png.open("rb") as stream:
                    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise SolveFailed("后处理未生成有效的 PNG。")
                limits = tuple(result[key] for key in ("legend_min_mpa", "legend_max_mpa", "peak_mpa"))
                if not all(isfinite(v) for v in limits) or limits[0] > limits[1] or limits[2] < 0:
                    raise SolveFailed("后处理返回的 S33 数值无效。")
                if result["odb_name"] != "clamp.odb" or result["averaging_threshold_percent"] != 75:
                    raise SolveFailed("后处理未返回约定的 ODB 或平均阈值。")
                self.clean_scratch(folder)
                self.update(job_id, "done", 100, "求解和云图导出完成。", result)
            except Exception as error:
                message = str(error) if isinstance(error, SolveFailed) else "作业或后处理失败，请查看本机作业日志。"
                try:
                    if folder.is_dir():
                        with (folder / "failure.log").open("a", encoding="utf-8") as log:
                            log.write(type(error).__name__ + ": " + str(error) + "\n")
                        self.clean_failed(folder)
                finally:
                    self.update(job_id, "failed", 0, message)
