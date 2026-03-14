from backend.builder.image_builder import _compute_target_image
from backend.core.database import init_db, save_task
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    StageStatus,
    TaskStatus,
)

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from backend.core.task_manager import TaskManager


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database for tests."""
    path = str(tmp_path / "test_tasks.db")
    init_db(path)
    return path


def _make_manager(db_path):
    """Create a TaskManager with a temporary DB and mocked prune."""
    with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock):
        return TaskManager(db_path=db_path)


class TestComputeTargetImage:
    def test_simple(self):
        result = _compute_target_image("registry.sensecore.tech/ccr-sandbox-swe", "ubuntu:22.04")
        assert result == "registry.sensecore.tech/ccr-sandbox-swe/ubuntu:22.04"

    def test_with_multi_segment_base(self):
        result = _compute_target_image(
            "registry.sensecore.tech/ccr-sandbox-swe",
            "nikolaik/python-nodejs:python3.12-nodejs22"
        )
        assert result == "registry.sensecore.tech/ccr-sandbox-swe/nikolaik_python-nodejs:python3.12-nodejs22"

    def test_strip_registry_prefix(self):
        result = _compute_target_image(
            "registry.sensecore.tech/ccr-sandbox-swe",
            "docker.io/library/ubuntu:22.04"
        )
        assert result == "registry.sensecore.tech/ccr-sandbox-swe/library_ubuntu:22.04"

    def test_no_tag(self):
        result = _compute_target_image("registry.sensecore.tech/repo", "ubuntu")
        assert result == "registry.sensecore.tech/repo/ubuntu:latest"

    def test_trailing_slash(self):
        result = _compute_target_image("registry.sensecore.tech/repo/", "ubuntu:22.04")
        assert result == "registry.sensecore.tech/repo/ubuntu:22.04"


class TestTaskModels:
    def test_task_properties(self):
        task = BuildTask(
            task_name="test",
            deps_image="deps:latest",
            push_dir="reg/repo",
            base_images=["a:1", "b:2"],
        )
        task.images = [
            ImageBuildInfo(base_image="a:1", target_image="reg/repo/a:1", status=ImageBuildStatus.SUCCESS),
            ImageBuildInfo(base_image="b:2", target_image="reg/repo/b:2", status=ImageBuildStatus.FAILED),
        ]
        assert task.total_images == 2
        assert task.completed_images == 1
        assert task.failed_images == 1

    def test_image_current_stage(self):
        img = ImageBuildInfo(base_image="a:1", target_image="reg/a:1")
        assert img.current_stage is None
        img.stages[1].status = StageStatus.RUNNING
        assert img.current_stage == "docker_build"


class TestStopTask:
    @pytest.mark.asyncio
    async def test_stop_running_task(self, db_path):
        manager = _make_manager(db_path)

        # Mock prep_shared_build_context and build_image to block forever
        async def slow_build(*args, **kwargs):
            await asyncio.sleep(3600)

        with patch("backend.core.task_manager.prep_shared_build_context", return_value="/tmp/fake"):
            with patch.object(manager.image_builder, "build_image", side_effect=slow_build):
                with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock):
                    task = await manager.create_task(
                        task_name="stop-test",
                        deps_image="deps:latest",
                        base_images=["ubuntu:22.04"],
                        push_dir="reg/repo",
                    )
                    # Let the task start running
                    await asyncio.sleep(0.1)
                    assert task.status == TaskStatus.RUNNING

                    # Stop it
                    success, msg = await manager.stop_task(task.task_id)
                    assert success is True

                    # Wait for cancellation to propagate
                    await asyncio.sleep(0.1)
                    assert task.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_stop_nonexistent_task(self, db_path):
        manager = _make_manager(db_path)
        success, msg = await manager.stop_task("nonexistent")
        assert success is False
        assert "不存在" in msg

    @pytest.mark.asyncio
    async def test_stop_completed_task(self, db_path):
        manager = _make_manager(db_path)

        with patch("backend.core.task_manager.prep_shared_build_context", return_value="/tmp/fake"):
            with patch.object(manager.image_builder, "build_image", new_callable=AsyncMock):
                with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock):
                    task = await manager.create_task(
                        task_name="done-test",
                        deps_image="deps:latest",
                        base_images=["ubuntu:22.04"],
                        push_dir="reg/repo",
                    )
                    # Wait for task to finish
                    await asyncio.sleep(0.2)

                    success, msg = await manager.stop_task(task.task_id)
                    assert success is False


class TestTaskRestore:
    def test_restore_running_task_marked_as_failed(self, db_path):
        """Tasks that were running when server stopped should be marked as failed."""
        task = BuildTask(
            task_name="interrupted",
            deps_image="deps:latest",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
            status=TaskStatus.RUNNING,
        )
        task.images.append(
            ImageBuildInfo(
                base_image="ubuntu:22.04",
                target_image="reg/repo/ubuntu:22.04",
                status=ImageBuildStatus.BUILDING,
            )
        )
        save_task(task, db_path)

        # Create a new manager which triggers restore
        manager = _make_manager(db_path)

        restored = manager.get_task(task.task_id)
        assert restored is not None
        assert restored.status == TaskStatus.FAILED
        assert restored.finished_at is not None
        assert restored.images[0].status == ImageBuildStatus.FAILED
        assert "Server restarted" in restored.images[0].error_message

    def test_restore_completed_task_unchanged(self, db_path):
        """Completed tasks should remain completed after restore."""
        task = BuildTask(
            task_name="done",
            deps_image="deps:latest",
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

        manager = _make_manager(db_path)

        restored = manager.get_task(task.task_id)
        assert restored is not None
        assert restored.status == TaskStatus.COMPLETED
        assert restored.images[0].status == ImageBuildStatus.SUCCESS

    def test_restore_empty_db(self, db_path):
        """Manager should start fine with an empty DB."""
        manager = _make_manager(db_path)
        assert manager.list_tasks() == []

    @pytest.mark.asyncio
    async def test_task_persisted_after_create(self, db_path):
        """Created task should be saved to DB."""
        manager = _make_manager(db_path)

        with patch("backend.core.task_manager.prep_shared_build_context", return_value="/tmp/fake"):
            with patch.object(manager.image_builder, "build_image", new_callable=AsyncMock):
                with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock):
                    task = await manager.create_task(
                        task_name="persist-test",
                        deps_image="deps:latest",
                        base_images=["ubuntu:22.04"],
                        push_dir="reg/repo",
                    )
                    await asyncio.sleep(0.2)

        # Create a new manager from the same DB
        manager2 = _make_manager(db_path)
        restored = manager2.get_task(task.task_id)
        assert restored is not None
        assert restored.task_name == "persist-test"
