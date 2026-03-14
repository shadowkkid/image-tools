from unittest.mock import AsyncMock, patch
import pytest

from backend.builder.image_builder import (
    ImageBuilder,
    _compute_target_image,
    prep_shared_build_context,
)
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    StageStatus,
)


@pytest.fixture
def source_dir(tmp_path):
    """Create a mock OpenHands source directory."""
    src = tmp_path / "OpenHands_Ss"
    (src / "openhands").mkdir(parents=True)
    (src / "openhands" / "__init__.py").write_text("")
    (src / "openhands" / "core").mkdir()
    (src / "openhands" / "core" / "test.py").write_text("# test")
    # Add node_modules to verify it gets filtered
    (src / "openhands" / "integrations" / "vscode" / "node_modules" / "pkg").mkdir(parents=True)
    (src / "openhands" / "integrations" / "vscode" / "node_modules" / "pkg" / "big.js").write_text("x" * 1000)
    (src / "microagents").mkdir()
    (src / "microagents" / "agent.md").write_text("# agent")
    (src / "pyproject.toml").write_text("[tool.poetry]\nname='test'")
    (src / "poetry.lock").write_text("# lock")
    return str(src)


@pytest.fixture
def shared_dir(source_dir):
    """Prepare shared build context from source."""
    d = prep_shared_build_context(source_dir)
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def task(source_dir):
    return BuildTask(
        task_name="test-build",
        deps_image="deps:latest",
        push_dir="registry.example.com/repo",
        base_images=["ubuntu:22.04"],
        build_args=["--network=host"],
        retry_count=1,
        source_dir=source_dir,
    )


@pytest.fixture
def image_info():
    return ImageBuildInfo(
        base_image="ubuntu:22.04",
        target_image="registry.example.com/repo/ubuntu:22.04",
    )


class TestPrepSharedBuildContext:
    def test_copies_source_files(self, shared_dir):
        import os
        code_dir = os.path.join(shared_dir, "code")
        assert os.path.isdir(os.path.join(code_dir, "openhands"))
        assert os.path.isdir(os.path.join(code_dir, "microagents"))
        assert os.path.isfile(os.path.join(code_dir, "pyproject.toml"))
        assert os.path.isfile(os.path.join(code_dir, "poetry.lock"))

    def test_filters_node_modules(self, shared_dir):
        import os
        code_dir = os.path.join(shared_dir, "code")
        # node_modules should NOT exist
        assert not os.path.exists(
            os.path.join(code_dir, "openhands", "integrations", "vscode", "node_modules")
        )
        # But the integrations/vscode dir itself should exist (without node_modules)
        assert os.path.isdir(
            os.path.join(code_dir, "openhands", "integrations", "vscode")
        )


class TestImageBuilder:
    @pytest.mark.asyncio
    async def test_build_success(self, task, image_info, shared_dir):
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
                    await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.SUCCESS
        assert all(s.status == StageStatus.SUCCESS for s in image_info.stages)
        assert image_info.finished_at is not None

    @pytest.mark.asyncio
    async def test_build_failure_with_retry(self, task, image_info, shared_dir):
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
                    await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.SUCCESS
        assert image_info.retry_attempts == 1

    @pytest.mark.asyncio
    async def test_build_all_retries_exhausted(self, task, image_info, shared_dir):
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(False, "ERROR: always fails", ["ERROR: always fails"])):
            await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.FAILED
        assert "docker_build" in (image_info.error_message or "")

    @pytest.mark.asyncio
    async def test_push_failure(self, task, image_info, shared_dir):
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
                    await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.FAILED
        assert "docker_push" in (image_info.error_message or "")
