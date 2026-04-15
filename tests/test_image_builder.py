from unittest.mock import AsyncMock, call, patch
import pytest

from backend.builder.image_builder import (
    ImageBuilder,
    _compute_script_target_image,
    _compute_target_image,
    prep_shared_build_context,
)
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    SCRIPT_BUILD_STAGES,
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
                          return_value=(True, "Build OK", ["Build OK"])), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(True, "Push OK")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")) as mock_remove, \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.SUCCESS
        assert all(s.status == StageStatus.SUCCESS for s in image_info.stages)
        assert image_info.finished_at is not None
        # Verify cleanup: build tag + target tag (push succeeded)
        assert mock_remove.call_count == 2

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

        with patch.object(builder.docker_service, "build", side_effect=mock_build), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(True, "Push OK")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")), \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.SUCCESS
        assert image_info.retry_attempts == 1

    @pytest.mark.asyncio
    async def test_build_all_retries_exhausted(self, task, image_info, shared_dir):
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(False, "ERROR: always fails", ["ERROR: always fails"])), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")), \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.FAILED
        assert "docker_build" in (image_info.error_message or "")

    @pytest.mark.asyncio
    async def test_push_failure(self, task, image_info, shared_dir):
        task.retry_count = 0
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(False, "push denied")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")) as mock_remove, \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        assert image_info.status == ImageBuildStatus.FAILED
        assert "docker_push" in (image_info.error_message or "")
        # Only build tag cleaned (push failed, target tag not removed)
        assert mock_remove.call_count == 1


class TestImageCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_on_success_removes_both_tags(self, task, image_info, shared_dir):
        """After successful push, both build tag and target tag should be removed."""
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(True, "Push OK")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")) as mock_remove, \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        calls = mock_remove.call_args_list
        # First call: build tag
        assert "image-tools-build/" in calls[0].args[0]
        # Second call: target image
        assert calls[1].args[0] == image_info.target_image

    @pytest.mark.asyncio
    async def test_cleanup_on_push_failure_only_removes_build_tag(self, task, image_info, shared_dir):
        """When push fails, only build tag should be removed (target tag kept for debugging)."""
        task.retry_count = 0
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(False, "push denied")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")) as mock_remove, \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        # Only the build tag should be removed
        assert mock_remove.call_count == 1
        assert "image-tools-build/" in mock_remove.call_args.args[0]

    @pytest.mark.asyncio
    async def test_cleanup_on_build_failure_removes_build_tag(self, task, image_info, shared_dir):
        """When build fails, build tag cleanup should still be attempted."""
        task.retry_count = 0
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(False, "ERROR: fail", ["ERROR: fail"])), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")) as mock_remove, \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")):
            await builder.build_image(image_info, task, shared_dir)

        # Build tag removal attempted (best-effort)
        assert mock_remove.call_count == 1
        assert "image-tools-build/" in mock_remove.call_args.args[0]

    @pytest.mark.asyncio
    async def test_cleanup_does_not_prune_build_cache_per_image(self, task, image_info, shared_dir):
        """prune_build_cache should NOT be called per-image; it runs once at task level."""
        task.retry_count = 0
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(True, "Push OK")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")), \
             patch.object(builder.docker_service, "prune_build_cache",
                          new_callable=AsyncMock,
                          return_value=(True, "Pruned")) as mock_prune_cache:
            await builder.build_image(image_info, task, shared_dir)

        mock_prune_cache.assert_not_called()


class TestComputeScriptTargetImage:
    def test_append_mode(self):
        result = _compute_script_target_image("registry.example.com/repo/ubuntu:22.04", "append", "-custom")
        assert result == "registry.example.com/repo/ubuntu:22.04-custom"

    def test_replace_mode(self):
        result = _compute_script_target_image("registry.example.com/repo/ubuntu:22.04", "replace", "v2.0")
        assert result == "registry.example.com/repo/ubuntu:v2.0"

    def test_append_no_tag(self):
        result = _compute_script_target_image("registry.example.com/repo/ubuntu", "append", "-custom")
        assert result == "registry.example.com/repo/ubuntu:latest-custom"

    def test_replace_no_tag(self):
        result = _compute_script_target_image("registry.example.com/repo/ubuntu", "replace", "v1")
        assert result == "registry.example.com/repo/ubuntu:v1"

    def test_append_empty_suffix(self):
        result = _compute_script_target_image("ubuntu:22.04", "append", "")
        assert result == "ubuntu:22.04"

    def test_replace_with_complex_image(self):
        result = _compute_script_target_image(
            "registry.cn-sh-01.sensecore.cn/ccr-swe/sweb.eval:python3.12",
            "replace",
            "patched",
        )
        assert result == "registry.cn-sh-01.sensecore.cn/ccr-swe/sweb.eval:patched"


class TestScriptBuildPipeline:
    @pytest.fixture
    def script_task(self):
        return BuildTask(
            task_name="script-test",
            deps_image="",
            push_dir="",
            base_images=["registry.example.com/repo/ubuntu:22.04"],
            build_mode="script",
            dockerfile_content="FROM {{BASE_IMAGE}}\nRUN echo hello",
            tag_mode="append",
            tag_suffix="-custom",
        )

    @pytest.fixture
    def script_image_info(self):
        return ImageBuildInfo(
            base_image="registry.example.com/repo/ubuntu:22.04",
            target_image="registry.example.com/repo/ubuntu:22.04-custom",
            stage_names=SCRIPT_BUILD_STAGES,
        )

    @pytest.mark.asyncio
    async def test_script_build_success(self, script_task, script_image_info):
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(True, "Build OK", ["Build OK"])), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(True, "Push OK")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")):
            await builder.script_build_image(script_image_info, script_task)

        assert script_image_info.status == ImageBuildStatus.SUCCESS
        assert all(s.status == StageStatus.SUCCESS for s in script_image_info.stages)

    @pytest.mark.asyncio
    async def test_script_build_failure(self, script_task, script_image_info):
        script_task.retry_count = 0
        builder = ImageBuilder()

        with patch.object(builder.docker_service, "build",
                          new_callable=AsyncMock,
                          return_value=(False, "ERROR: build failed", ["ERROR: build failed"])), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")):
            await builder.script_build_image(script_image_info, script_task)

        assert script_image_info.status == ImageBuildStatus.FAILED
        assert "docker_build" in (script_image_info.error_message or "")

    @pytest.mark.asyncio
    async def test_script_build_dockerfile_rendered(self, script_task, script_image_info):
        """Verify the Dockerfile template is rendered with the actual base image."""
        builder = ImageBuilder()
        rendered_content = None

        async def mock_build(build_context_path, tags, **kwargs):
            nonlocal rendered_content
            import os
            dockerfile_path = os.path.join(build_context_path, "Dockerfile")
            with open(dockerfile_path) as f:
                rendered_content = f.read()
            return (True, "Build OK", ["Build OK"])

        with patch.object(builder.docker_service, "build", side_effect=mock_build), \
             patch.object(builder.docker_service, "tag",
                          new_callable=AsyncMock,
                          return_value=(True, "Tag OK")), \
             patch.object(builder.docker_service, "push",
                          new_callable=AsyncMock,
                          return_value=(True, "Push OK")), \
             patch.object(builder.docker_service, "remove_image",
                          new_callable=AsyncMock,
                          return_value=(True, "Removed")):
            await builder.script_build_image(script_image_info, script_task)

        assert rendered_content is not None
        assert "FROM registry.example.com/repo/ubuntu:22.04" in rendered_content
        assert "{{BASE_IMAGE}}" not in rendered_content
