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
                finished_at TEXT,
                dataset TEXT NOT NULL DEFAULT '',
                agent TEXT NOT NULL DEFAULT '',
                agent_version TEXT NOT NULL DEFAULT '',
                build_mode TEXT NOT NULL DEFAULT 'build'
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

            CREATE TABLE IF NOT EXISTS datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                agent TEXT NOT NULL DEFAULT '',
                agent_version TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(name, agent, agent_version)
            );

            CREATE TABLE IF NOT EXISTS dataset_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id INTEGER NOT NULL,
                image_name TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
        """)

        # Migrations for existing databases
        task_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "dataset" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN dataset TEXT NOT NULL DEFAULT ''")
        if "agent" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN agent TEXT NOT NULL DEFAULT ''")
        if "agent_version" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN agent_version TEXT NOT NULL DEFAULT ''")
        if "build_mode" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN build_mode TEXT NOT NULL DEFAULT 'build'")

        ds_cols = {row["name"] for row in conn.execute("PRAGMA table_info(datasets)").fetchall()}
        if "agent" not in ds_cols:
            conn.execute("ALTER TABLE datasets ADD COLUMN agent TEXT NOT NULL DEFAULT ''")
        if "agent_version" not in ds_cols:
            conn.execute("ALTER TABLE datasets ADD COLUMN agent_version TEXT NOT NULL DEFAULT ''")

        conn.commit()
    finally:
        conn.close()

    logger.info(f"Database initialized at {db_path}")
    return db_path


def save_task(task: BuildTask, db_path: str | None = None) -> None:
    """Save a task and its images/stages to the database.

    Uses INSERT OR REPLACE for the tasks row to avoid triggering ON DELETE CASCADE,
    which would wipe dataset_images linked to this task.
    """
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        # Manually delete child tables (stages → images) without touching the tasks row,
        # so that ON DELETE CASCADE on tasks does NOT fire against dataset_images.
        conn.execute(
            """DELETE FROM stages WHERE image_id IN (
                   SELECT id FROM images WHERE task_id = ?
               )""",
            (task.task_id,),
        )
        conn.execute("DELETE FROM images WHERE task_id = ?", (task.task_id,))

        # Upsert the tasks row — use UPDATE if exists, INSERT if new.
        # INSERT OR REPLACE would trigger ON DELETE CASCADE in SQLite, so we avoid it.
        existing = conn.execute(
            "SELECT 1 FROM tasks WHERE task_id = ?", (task.task_id,)
        ).fetchone()
        task_params = (
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
            task.dataset,
            task.agent,
            task.agent_version,
            task.build_mode,
        )
        if existing:
            conn.execute(
                """UPDATE tasks SET
                       task_name=?, deps_image=?, push_dir=?, base_images=?, build_args=?,
                       retry_count=?, concurrency=?, source_dir=?, status=?, created_at=?,
                       finished_at=?, dataset=?, agent=?, agent_version=?, build_mode=?
                   WHERE task_id = ?""",
                task_params + (task.task_id,),
            )
        else:
            conn.execute(
                """INSERT INTO tasks
                   (task_name, deps_image, push_dir, base_images, build_args,
                    retry_count, concurrency, source_dir, status, created_at,
                    finished_at, dataset, agent, agent_version, build_mode, task_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                task_params + (task.task_id,),
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
                agent=row["agent"] or "",
                agent_version=row["agent_version"] or "",
                dataset=row["dataset"] or "",
                build_args=json.loads(row["build_args"]),
                retry_count=row["retry_count"],
                concurrency=row["concurrency"],
                source_dir=row["source_dir"],
                build_mode=row["build_mode"] if "build_mode" in row.keys() else "build",
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


# ---- Dataset operations ----

def ensure_dataset(
    name: str, agent: str = "", agent_version: str = "", db_path: str | None = None
) -> int:
    """Get or create a dataset by (name, agent, agent_version). Returns the dataset id."""
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM datasets WHERE name = ? AND agent = ? AND agent_version = ?",
            (name, agent, agent_version),
        ).fetchone()
        if row:
            return row["id"]
        cursor = conn.execute(
            "INSERT INTO datasets (name, agent, agent_version, created_at) VALUES (?, ?, ?, ?)",
            (name, agent, agent_version, _dt_to_str(datetime.now())),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def add_dataset_image(
    dataset_name: str,
    image_name: str,
    task_id: str,
    agent: str = "",
    agent_version: str = "",
    db_path: str | None = None,
) -> None:
    """Add an image record to a dataset."""
    db_path = db_path or _DEFAULT_DB_PATH
    dataset_id = ensure_dataset(dataset_name, agent, agent_version, db_path)
    conn = _get_connection(db_path)
    try:
        existing = conn.execute(
            "SELECT 1 FROM dataset_images WHERE dataset_id = ? AND image_name = ? AND task_id = ?",
            (dataset_id, image_name, task_id),
        ).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO dataset_images (dataset_id, image_name, task_id, created_at) VALUES (?, ?, ?, ?)",
            (dataset_id, image_name, task_id, _dt_to_str(datetime.now())),
        )
        conn.commit()
    finally:
        conn.close()


def list_datasets(
    agent: str = "",
    agent_version: str = "",
    search: str = "",
    db_path: str | None = None,
) -> list[dict]:
    """List datasets with image counts, filtered by agent/version and optional name search."""
    db_path = db_path or _DEFAULT_DB_PATH
    if not os.path.exists(db_path):
        return []
    conn = _get_connection(db_path)
    try:
        query = """
            SELECT d.id, d.name, d.agent, d.agent_version, d.created_at,
                   COUNT(di.id) AS image_count
            FROM datasets d
            LEFT JOIN dataset_images di ON d.id = di.dataset_id
            WHERE 1=1
        """
        params: list = []
        if agent:
            query += " AND d.agent = ?"
            params.append(agent)
        if agent_version:
            query += " AND d.agent_version = ?"
            params.append(agent_version)
        if search:
            query += " AND d.name LIKE ?"
            params.append(f"%{search}%")
        query += " GROUP BY d.id ORDER BY d.created_at DESC"
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def list_dataset_images(
    dataset_id: int,
    search: str = "",
    page: int = 1,
    page_size: int = 50,
    db_path: str | None = None,
) -> tuple[list[dict], int]:
    """List images in a dataset with pagination. Returns (rows, total_count)."""
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        base = """
            FROM dataset_images di
            LEFT JOIN tasks t ON di.task_id = t.task_id
            WHERE di.dataset_id = ?
        """
        params: list = [dataset_id]
        if search:
            base += " AND di.image_name LIKE ?"
            params.append(f"%{search}%")

        total = conn.execute(f"SELECT COUNT(*) AS cnt {base}", params).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT di.id, di.image_name, di.task_id, t.task_name, di.created_at {base} ORDER BY di.created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def delete_task(task_id: str, db_path: str | None = None) -> bool:
    """Delete a task by task_id. Preserves dataset_images records."""
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        # Temporarily disable FK enforcement so CASCADE doesn't wipe dataset_images.
        # We manually clean up images/stages which are build-time data.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """DELETE FROM stages WHERE image_id IN (
                   SELECT id FROM images WHERE task_id = ?
               )""",
            (task_id,),
        )
        conn.execute("DELETE FROM images WHERE task_id = ?", (task_id,))
        cursor = conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_dataset(dataset_id: int, db_path: str | None = None) -> bool:
    """Delete a dataset by id. Returns True if a row was deleted."""
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_dataset_images(image_ids: list[int], db_path: str | None = None) -> int:
    """Delete dataset_images by ids. Returns the number of rows deleted."""
    if not image_ids:
        return 0
    db_path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(db_path)
    try:
        placeholders = ",".join("?" for _ in image_ids)
        cursor = conn.execute(
            f"DELETE FROM dataset_images WHERE id IN ({placeholders})", image_ids
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_dataset_by_id(dataset_id: int, db_path: str | None = None) -> dict | None:
    """Get a single dataset by id."""
    db_path = db_path or _DEFAULT_DB_PATH
    if not os.path.exists(db_path):
        return None
    conn = _get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
