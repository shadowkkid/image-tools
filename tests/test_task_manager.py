from backend.builder.image_builder import _compute_target_image
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
    async def test_stop_running_task(self):
        manager = TaskManager()

        # Mock prep_shared_build_context and build_image to block forever
        async def slow_build(*args, **kwargs):
            await asyncio.sleep(3600)

        with patch("backend.core.task_manager.prep_shared_build_context", return_value="/tmp/fake"):
            with patch.object(manager.image_builder, "build_image", side_effect=slow_build):
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
    async def test_stop_nonexistent_task(self):
        manager = TaskManager()
        success, msg = await manager.stop_task("nonexistent")
        assert success is False
        assert "不存在" in msg

    @pytest.mark.asyncio
    async def test_stop_completed_task(self):
        manager = TaskManager()

        with patch("backend.core.task_manager.prep_shared_build_context", return_value="/tmp/fake"):
            with patch("backend.core.task_manager.ImageBuilder") as MockBuilder:
                instance = MockBuilder.return_value
                instance.build_image = AsyncMock()

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
