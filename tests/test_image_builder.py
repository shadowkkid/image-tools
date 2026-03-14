from unittest.mock import AsyncMock, patch, MagicMock
import os
import pytest

from backend.builder.image_builder import ImageBuilder, _compute_target_image
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    StageStatus,
)


@pytest.fixture
def task(tmp_path):
    """Create a test task with a mock source directory."""
    source_dir = tmp_path / "OpenHands_Ss"
    (source_dir / "openhands").mkdir(parents=True)
    (source_dir / "openhands" / "__init__.py").write_text("")
    (source_dir / "openhands" / "core").mkdir()
    (source_dir / "openhands" / "core" / "test.py").write_text("# test")
    (source_dir / "microagents").mkdir()
    (source_dir / "microagents" / "agent.md").write_text("# agent")
    (source_dir / "pyproject.toml").write_text("[tool.poetry]\nname='test'")
    (source_dir / "poetry.lock").write_text("# lock")

    return BuildTask(
        task_name="test-build",
        deps_image="deps:latest",
        push_dir="registry.example.com/repo",
        base_images=["ubuntu:22.04"],
        build_args=["--network=host"],
        retry_count=1,
        source_dir=str(source_dir),
    )


@pytest.fixture
def image_info():
    return ImageBuildInfo(
        base_image="ubuntu:22.04",
        target_image="registry.example.com/repo/ubuntu:22.04",
    )


class TestImageBuilder:
    @pytest.mark.asyncio
    async def test_build_success(self, task, image_info):
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])):
            with patch.object(builder.docker_service, "tag",
                              new_callable=AsyncMock,
                              return_value=(True, "Tag OK")):
                with patch.object(builder.docker_service, "push",
                                  new_callable=AsyncMock,
                                  return_value=(True, "Push OK")):
                    await builder.build_image(image_info, task)

        assert image_info.status == ImageBuildStatus.SUCCESS
        assert all(s.status == StageStatus.SUCCESS for s in image_info.stages)
        assert image_info.finished_at is not None

    @pytest.mark.asyncio
    async def test_build_failure_with_retry(self, task, image_info):
        builder = ImageBuilder()

        call_count = 0

        async def mock_build(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return (False, "ERROR: build failed", ["ERROR: build failed"])
            return (True, "Build OK", ["Build OK"])

        with patch.object(builder.docker_service, "build", side_effect=mock_build):
            with patch.object(builder.docker_service, "tag",
                              new_callable=AsyncMock,
                              return_value=(True, "Tag OK")):
                with patch.object(builder.docker_service, "push",
                                  new_callable=AsyncMock,
                                  return_value=(True, "Push OK")):
                    await builder.build_image(image_info, task)

        assert image_info.status == ImageBuildStatus.SUCCESS
        assert image_info.retry_attempts == 1

    @pytest.mark.asyncio
    async def test_build_all_retries_exhausted(self, task, image_info):
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(False, "ERROR: always fails", ["ERROR: always fails"])):
            await builder.build_image(image_info, task)

        assert image_info.status == ImageBuildStatus.FAILED
        assert "docker_build" in (image_info.error_message or "")

    @pytest.mark.asyncio
    async def test_push_failure(self, task, image_info):
        task.retry_count = 0
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])):
            with patch.object(builder.docker_service, "tag",
                              new_callable=AsyncMock,
                              return_value=(True, "Tag OK")):
                with patch.object(builder.docker_service, "push",
                                  new_callable=AsyncMock,
                                  return_value=(False, "push denied")):
                    await builder.build_image(image_info, task)

        assert image_info.status == ImageBuildStatus.FAILED
        assert "docker_push" in (image_info.error_message or "")
