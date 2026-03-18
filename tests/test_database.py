import os
from datetime import datetime

import pytest

from backend.core.database import init_db, load_all_tasks, save_task, delete_task
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    StageName,
    StageStatus,
    TaskStatus,
)


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database."""
    path = str(tmp_path / "test_tasks.db")
    init_db(path)
    return path


class TestInitDb:
    def test_creates_db_file(self, tmp_path):
        path = str(tmp_path / "subdir" / "test.db")
        init_db(path)
        assert os.path.exists(path)

    def test_idempotent(self, db_path):
        # Calling init_db again should not fail
        init_db(db_path)


class TestSaveAndLoadTask:
    def test_save_and_load_basic_task(self, db_path):
        task = BuildTask(
            task_name="test-task",
            deps_image="deps:latest",
            push_dir="registry.example.com/repo",
            base_images=["ubuntu:22.04"],
            build_args=["--network=host"],
            retry_count=2,
            concurrency=3,
            source_dir="/tmp/src",
            status=TaskStatus.COMPLETED,
        )
        task.images.append(
            ImageBuildInfo(
                base_image="ubuntu:22.04",
                target_image="registry.example.com/repo/ubuntu:22.04",
                status=ImageBuildStatus.SUCCESS,
            )
        )
        task.finished_at = datetime.now()

        save_task(task, db_path)
        loaded = load_all_tasks(db_path)

        assert task.task_id in loaded
        t = loaded[task.task_id]
        assert t.task_name == "test-task"
        assert t.deps_image == "deps:latest"
        assert t.push_dir == "registry.example.com/repo"
        assert t.base_images == ["ubuntu:22.04"]
        assert t.build_args == ["--network=host"]
        assert t.retry_count == 2
        assert t.concurrency == 3
        assert t.source_dir == "/tmp/src"
        assert t.status == TaskStatus.COMPLETED
        assert t.finished_at is not None

    def test_save_and_load_images(self, db_path):
        task = BuildTask(
            task_name="img-test",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1", "b:2"],
        )
        img1 = ImageBuildInfo(
            base_image="a:1",
            target_image="reg/repo/a:1",
            status=ImageBuildStatus.SUCCESS,
            retry_attempts=1,
            started_at=datetime(2026, 1, 1, 10, 0, 0),
            finished_at=datetime(2026, 1, 1, 10, 5, 0),
        )
        img2 = ImageBuildInfo(
            base_image="b:2",
            target_image="reg/repo/b:2",
            status=ImageBuildStatus.FAILED,
            error_message="build error",
        )
        task.images = [img1, img2]

        save_task(task, db_path)
        loaded = load_all_tasks(db_path)

        t = loaded[task.task_id]
        assert len(t.images) == 2
        assert t.images[0].status == ImageBuildStatus.SUCCESS
        assert t.images[0].retry_attempts == 1
        assert t.images[1].status == ImageBuildStatus.FAILED
        assert t.images[1].error_message == "build error"

    def test_save_and_load_stages(self, db_path):
        task = BuildTask(
            task_name="stage-test",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
        )
        img = ImageBuildInfo(
            base_image="ubuntu:22.04",
            target_image="reg/repo/ubuntu:22.04",
        )
        # Modify some stages
        img.stages[0].status = StageStatus.SUCCESS
        img.stages[0].started_at = datetime(2026, 1, 1, 10, 0, 0)
        img.stages[0].finished_at = datetime(2026, 1, 1, 10, 0, 5)
        img.stages[1].status = StageStatus.FAILED
        img.stages[1].error_message = "build failed"
        task.images = [img]

        save_task(task, db_path)
        loaded = load_all_tasks(db_path)

        t = loaded[task.task_id]
        stages = t.images[0].stages
        assert len(stages) == 4
        assert stages[0].name == StageName.GENERATE_DOCKERFILE
        assert stages[0].status == StageStatus.SUCCESS
        assert stages[1].name == StageName.DOCKER_BUILD
        assert stages[1].status == StageStatus.FAILED
        assert stages[1].error_message == "build failed"
        assert stages[2].status == StageStatus.PENDING

    def test_save_overwrites_existing(self, db_path):
        task = BuildTask(
            task_name="overwrite-test",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
            status=TaskStatus.PENDING,
        )
        task.images.append(
            ImageBuildInfo(
                base_image="ubuntu:22.04",
                target_image="reg/repo/ubuntu:22.04",
            )
        )
        save_task(task, db_path)

        # Update and save again
        task.status = TaskStatus.COMPLETED
        task.images[0].status = ImageBuildStatus.SUCCESS
        save_task(task, db_path)

        loaded = load_all_tasks(db_path)
        assert len(loaded) == 1
        assert loaded[task.task_id].status == TaskStatus.COMPLETED
        assert loaded[task.task_id].images[0].status == ImageBuildStatus.SUCCESS

    def test_load_empty_db(self, db_path):
        loaded = load_all_tasks(db_path)
        assert loaded == {}

    def test_load_nonexistent_db(self, tmp_path):
        loaded = load_all_tasks(str(tmp_path / "nonexistent.db"))
        assert loaded == {}

    def test_multiple_tasks(self, db_path):
        for i in range(3):
            task = BuildTask(
                task_name=f"task-{i}",
                deps_image="deps:v1",
                push_dir="reg/repo",
                base_images=[f"img:{i}"],
            )
            task.images.append(
                ImageBuildInfo(
                    base_image=f"img:{i}",
                    target_image=f"reg/repo/img:{i}",
                )
            )
            save_task(task, db_path)

        loaded = load_all_tasks(db_path)
        assert len(loaded) == 3

    def test_datetime_roundtrip(self, db_path):
        now = datetime.now()
        task = BuildTask(
            task_name="dt-test",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1"],
            created_at=now,
        )
        task.finished_at = now
        task.images.append(
            ImageBuildInfo(
                base_image="a:1",
                target_image="reg/repo/a:1",
                started_at=now,
                finished_at=now,
            )
        )

        save_task(task, db_path)
        loaded = load_all_tasks(db_path)
        t = loaded[task.task_id]

        # Microsecond precision should be preserved
        assert t.created_at == now
        assert t.finished_at == now
        assert t.images[0].started_at == now
        assert t.images[0].finished_at == now


class TestDeleteTask:
    def test_delete_existing_task(self, db_path):
        task = BuildTask(
            task_name="to-delete",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
            status=TaskStatus.COMPLETED,
        )
        task.images.append(
            ImageBuildInfo(
                base_image="ubuntu:22.04",
                target_image="reg/repo/ubuntu:22.04",
                status=ImageBuildStatus.SUCCESS,
            )
        )
        save_task(task, db_path)

        result = delete_task(task.task_id, db_path)
        assert result is True

        loaded = load_all_tasks(db_path)
        assert task.task_id not in loaded

    def test_delete_nonexistent_task(self, db_path):
        result = delete_task("nonexistent-id", db_path)
        assert result is False

    def test_delete_cascades_images_and_stages(self, db_path):
        task = BuildTask(
            task_name="cascade-test",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1", "b:2"],
        )
        task.images = [
            ImageBuildInfo(base_image="a:1", target_image="reg/repo/a:1"),
            ImageBuildInfo(base_image="b:2", target_image="reg/repo/b:2"),
        ]
        save_task(task, db_path)

        # Verify task exists with images
        loaded = load_all_tasks(db_path)
        assert len(loaded[task.task_id].images) == 2

        delete_task(task.task_id, db_path)
        loaded = load_all_tasks(db_path)
        assert task.task_id not in loaded
