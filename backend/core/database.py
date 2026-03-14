import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.core.task_models import (
    ALL_STAGES,
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    StageInfo,
    StageName,
    StageStatus,
    TaskStatus,
)

logger = logging.getLogger(__name__)

# Default DB path: backend/data/tasks.db
_DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "tasks.db")

_DATETIME_FMT = "%Y-%m-%d %H:%M:%S.%f"


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.strftime(_DATETIME_FMT) if dt else None


def _str_to_dt(s: str | None) -> datetime | None:
    return datetime.strptime(s, _DATETIME_FMT) if s else None


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | None = None) -> str:
    """Initialize the database schema. Returns the db_path used."""
    db_path = db_path or _DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = _get_connection(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_name TEXT NOT NULL,
                deps_image TEXT NOT NULL,
                push_dir TEXT NOT NULL,
                base_images TEXT NOT NULL,
                build_args TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                concurrency INTEGER NOT NULL DEFAULT 1,
                source_dir TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                base_image TEXT NOT NULL,
                target_image TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_attempts INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );
        """)
        conn.commit()
    finally:
        conn.close()

    logger.info(f"Database initialized at {db_path}")
    return db_path


def save_task(task: BuildTask, db_path: str | None = None) -> None:
    """Save a task and its images/stages to the database (DELETE + INSERT)."""
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        # Delete existing data for this task (cascade deletes images and stages)
        conn.execute("DELETE FROM tasks WHERE task_id = ?", (task.task_id,))

        # Insert task
        conn.execute(
            """INSERT INTO tasks
               (task_id, task_name, deps_image, push_dir, base_images, build_args,
                retry_count, concurrency, source_dir, status, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.task_id,
                task.task_name,
                task.deps_image,
                task.push_dir,
                json.dumps(task.base_images),
                json.dumps(task.build_args),
                task.retry_count,
                task.concurrency,
                task.source_dir,
                task.status.value,
                _dt_to_str(task.created_at),
                _dt_to_str(task.finished_at),
            ),
        )

        # Insert images and stages
        for img in task.images:
            cursor = conn.execute(
                """INSERT INTO images
                   (task_id, base_image, target_image, status, retry_attempts,
                    error_message, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.task_id,
                    img.base_image,
                    img.target_image,
                    img.status.value,
                    img.retry_attempts,
                    img.error_message,
                    _dt_to_str(img.started_at),
                    _dt_to_str(img.finished_at),
                ),
            )
            image_id = cursor.lastrowid

            for stage in img.stages:
                conn.execute(
                    """INSERT INTO stages
                       (image_id, name, status, error_message, started_at, finished_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        image_id,
                        stage.name.value,
                        stage.status.value,
                        stage.error_message,
                        _dt_to_str(stage.started_at),
                        _dt_to_str(stage.finished_at),
                    ),
                )

        conn.commit()
    finally:
        conn.close()


def load_all_tasks(db_path: str | None = None) -> dict[str, BuildTask]:
    """Load all tasks from database, rebuilding dataclass objects."""
    db_path = db_path or _DEFAULT_DB_PATH

    if not os.path.exists(db_path):
        return {}

    conn = _get_connection(db_path)
    try:
        tasks: dict[str, BuildTask] = {}

        for row in conn.execute("SELECT * FROM tasks").fetchall():
            task = BuildTask(
                task_name=row["task_name"],
                deps_image=row["deps_image"],
                push_dir=row["push_dir"],
                base_images=json.loads(row["base_images"]),
                build_args=json.loads(row["build_args"]),
                retry_count=row["retry_count"],
                concurrency=row["concurrency"],
                source_dir=row["source_dir"],
                task_id=row["task_id"],
                status=TaskStatus(row["status"]),
                images=[],
                created_at=_str_to_dt(row["created_at"]),
                finished_at=_str_to_dt(row["finished_at"]),
            )

            # Load images for this task
            img_rows = conn.execute(
                "SELECT * FROM images WHERE task_id = ? ORDER BY id", (task.task_id,)
            ).fetchall()

            for img_row in img_rows:
                img = ImageBuildInfo(
                    base_image=img_row["base_image"],
                    target_image=img_row["target_image"],
                    status=ImageBuildStatus(img_row["status"]),
                    retry_attempts=img_row["retry_attempts"],
                    error_message=img_row["error_message"],
                    started_at=_str_to_dt(img_row["started_at"]),
                    finished_at=_str_to_dt(img_row["finished_at"]),
                )

                # Load stages from DB and replace the defaults from __post_init__
                stage_rows = conn.execute(
                    "SELECT * FROM stages WHERE image_id = ? ORDER BY id",
                    (img_row["id"],),
                ).fetchall()

                if stage_rows:
                    img.stages = [
                        StageInfo(
                            name=StageName(sr["name"]),
                            status=StageStatus(sr["status"]),
                            error_message=sr["error_message"],
                            started_at=_str_to_dt(sr["started_at"]),
                            finished_at=_str_to_dt(sr["finished_at"]),
                        )
                        for sr in stage_rows
                    ]

                task.images.append(img)

            tasks[task.task_id] = task

        return tasks
    finally:
        conn.close()
