from backend.builder.image_builder import _compute_target_image
from backend.core.database import init_db, save_task
from backend.core.docker_service import DockerService
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
    """Create a TaskManager with a temporary DB and mocked external calls."""
    with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock), \
         patch("backend.core.task_manager.DockerService.manifest_exists", return_value=False):
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
        assert result == "registry.sensecore.tech/ccr-sandbox-swe/nikolaik/python-nodejs:python3.12-nodejs22"

    def test_strip_registry_prefix(self):
        result = _compute_target_image(
            "registry.sensecore.tech/ccr-sandbox-swe",
            "docker.io/library/ubuntu:22.04"
        )
        assert result == "registry.sensecore.tech/ccr-sandbox-swe/library/ubuntu:22.04"

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
                        agent="OpenHands",
                        agent_version="0.54.0",
                        dataset="test-ds",
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
                        agent="OpenHands",
                        agent_version="0.54.0",
                        dataset="test-ds",
                        base_images=["ubuntu:22.04"],
                        push_dir="reg/repo",
                    )
                    # Wait for task to finish
                    await asyncio.sleep(0.2)

                    success, msg = await manager.stop_task(task.task_id)
                    assert success is False


class TestTaskRestore:
    def test_restore_running_task_marked_as_failed(self, db_path):
        """Tasks that were running when server stopped should be marked as failed
        if images are not in the registry."""
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

        # manifest_exists returns False (default in _make_manager) -> marked as failed
        manager = _make_manager(db_path)

        restored = manager.get_task(task.task_id)
        assert restored is not None
        assert restored.status == TaskStatus.FAILED
        assert restored.finished_at is not None
        assert restored.images[0].status == ImageBuildStatus.FAILED
        assert "Server restarted" in restored.images[0].error_message

    def test_restore_recovers_images_from_registry(self, db_path):
        """BUILDING images that exist in the registry should be recovered as SUCCESS."""
        task = BuildTask(
            task_name="recoverable",
            deps_image="deps:latest",
            push_dir="reg/repo",
            base_images=["a:1", "b:2"],
            status=TaskStatus.RUNNING,
        )
        task.images = [
            ImageBuildInfo(
                base_image="a:1",
                target_image="reg/repo/a:1",
                status=ImageBuildStatus.BUILDING,
            ),
            ImageBuildInfo(
                base_image="b:2",
                target_image="reg/repo/b:2",
                status=ImageBuildStatus.BUILDING,
            ),
        ]
        save_task(task, db_path)

        # a:1 exists in registry, b:2 does not
        def mock_manifest(image):
            return image == "reg/repo/a:1"

        with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock), \
             patch("backend.core.task_manager.DockerService.manifest_exists", side_effect=mock_manifest):
            manager = TaskManager(db_path=db_path)

        restored = manager.get_task(task.task_id)
        assert restored.status == TaskStatus.PARTIAL_FAILED
        assert restored.images[0].status == ImageBuildStatus.SUCCESS
        assert restored.images[0].error_message is None
        assert restored.images[1].status == ImageBuildStatus.FAILED

    def test_restore_all_recovered_marks_completed(self, db_path):
        """If all BUILDING images are recovered from registry, task should be COMPLETED."""
        task = BuildTask(
            task_name="all-recovered",
            deps_image="deps:latest",
            push_dir="reg/repo",
            base_images=["a:1"],
            status=TaskStatus.RUNNING,
        )
        task.images = [
            ImageBuildInfo(
                base_image="a:1",
                target_image="reg/repo/a:1",
                status=ImageBuildStatus.BUILDING,
            ),
        ]
        save_task(task, db_path)

        with patch("backend.core.task_manager.DockerService.prune_images", new_callable=AsyncMock), \
             patch("backend.core.task_manager.DockerService.manifest_exists", return_value=True):
            manager = TaskManager(db_path=db_path)

        restored = manager.get_task(task.task_id)
        assert restored.status == TaskStatus.COMPLETED
        assert restored.images[0].status == ImageBuildStatus.SUCCESS

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
                        agent="OpenHands",
                        agent_version="0.54.0",
                        dataset="test-ds",
                        base_images=["ubuntu:22.04"],
                        push_dir="reg/repo",
                    )
                    await asyncio.sleep(0.2)

        # Create a new manager from the same DB
        manager2 = _make_manager(db_path)
        restored = manager2.get_task(task.task_id)
        assert restored is not None
        assert restored.task_name == "persist-test"


class TestImageRefCounting:
    def test_get_task_images(self):
        """_get_task_images deduplicates base images and excludes deps_image."""
        task = BuildTask(
            task_name="t",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04", "ubuntu:22.04", "alpine:3"],
        )
        result = TaskManager._get_task_images(task)
        assert result == {"ubuntu:22.04", "alpine:3"}

    def test_get_task_images_empty_deps(self):
        """Empty deps_image is excluded from the set."""
        task = BuildTask(
            task_name="t",
            deps_image="",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
        )
        result = TaskManager._get_task_images(task)
        assert result == {"ubuntu:22.04"}

    def test_get_task_images_excludes_deps(self):
        """deps_image is never included in tracked images (kept cached on disk)."""
        task = BuildTask(
            task_name="t",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
        )
        result = TaskManager._get_task_images(task)
        assert result == {"ubuntu:22.04"}
        assert "deps:v1" not in result

    @pytest.mark.asyncio
    async def test_register_and_unregister(self, db_path):
        """Single task register/unregister lifecycle."""
        manager = _make_manager(db_path)
        task = BuildTask(
            task_name="t",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
        )

        await manager._register_task_images(task)
        assert manager._image_refs == {"ubuntu:22.04": 1}

        removed = await manager._unregister_task_images(task)
        assert set(removed) == {"ubuntu:22.04"}
        assert manager._image_refs == {}

    @pytest.mark.asyncio
    async def test_shared_image_not_removed_while_referenced(self, db_path):
        """Shared base image is only returned for removal when last reference drops."""
        manager = _make_manager(db_path)
        task1 = BuildTask(
            task_name="t1",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
        )
        task2 = BuildTask(
            task_name="t2",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04", "alpine:3"],
        )

        await manager._register_task_images(task1)
        await manager._register_task_images(task2)
        assert manager._image_refs["ubuntu:22.04"] == 2
        assert "deps:v1" not in manager._image_refs  # deps_image not tracked
        assert manager._image_refs["alpine:3"] == 1

        # First unregister: shared ubuntu stays
        removed1 = await manager._unregister_task_images(task1)
        assert "ubuntu:22.04" not in removed1
        assert manager._image_refs["ubuntu:22.04"] == 1

        # Second unregister: all base images drop to zero
        removed2 = await manager._unregister_task_images(task2)
        assert set(removed2) == {"ubuntu:22.04", "alpine:3"}
        assert manager._image_refs == {}

    @pytest.mark.asyncio
    async def test_cleanup_calls_remove_and_prune(self, db_path):
        """_cleanup_task_images calls remove_image for each unreferenced image and prune."""
        manager = _make_manager(db_path)
        task = BuildTask(
            task_name="t",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
        )

        await manager._register_task_images(task)

        with patch.object(DockerService, "remove_image", new_callable=AsyncMock) as mock_remove, \
             patch.object(DockerService, "prune_images", new_callable=AsyncMock) as mock_prune:
            await manager._cleanup_task_images(task)

            removed_images = {call.args[0] for call in mock_remove.call_args_list}
            assert removed_images == {"ubuntu:22.04"}
            assert "deps:v1" not in removed_images
            mock_prune.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_task_cleans_up(self, db_path):
        """Cancelled task still goes through image cleanup in finally block."""
        manager = _make_manager(db_path)

        async def slow_build(*args, **kwargs):
            await asyncio.sleep(3600)

        with patch("backend.core.task_manager.prep_shared_build_context", return_value="/tmp/fake"), \
             patch.object(manager.image_builder, "build_image", side_effect=slow_build), \
             patch.object(DockerService, "remove_image", new_callable=AsyncMock) as mock_remove, \
             patch.object(DockerService, "prune_images", new_callable=AsyncMock) as mock_prune:
            task = await manager.create_task(
                task_name="cancel-cleanup-test",
                agent="OpenHands",
                agent_version="0.54.0",
                dataset="test-ds",
                base_images=["ubuntu:22.04"],
                push_dir="reg/repo",
            )
            await asyncio.sleep(0.1)
            assert task.status == TaskStatus.RUNNING
            # Images should be registered
            assert manager._image_refs.get("ubuntu:22.04", 0) >= 1

            # Cancel the task
            success, _ = await manager.stop_task(task.task_id)
            assert success is True
            await asyncio.sleep(0.1)

            assert task.status == TaskStatus.CANCELLED
            # Refs should be cleaned up
            assert manager._image_refs.get("ubuntu:22.04", 0) == 0
            # remove_image and prune should have been called
            mock_remove.assert_called()
            mock_prune.assert_called()
