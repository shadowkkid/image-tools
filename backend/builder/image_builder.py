import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from backend.builder.dockerfile_generator import DockerfileGenerator
from backend.core.docker_service import DockerService
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    StageName,
    StageStatus,
)

logger = logging.getLogger(__name__)

SYNTAX_DIRECTIVE = "# syntax=docker/dockerfile:1\n"

SCRIPT_BASE_IMAGE_PLACEHOLDER = "{{BASE_IMAGE}}"


def _ensure_syntax_directive(dockerfile_path: str) -> None:
    """Prepend BuildKit syntax directive if missing, enabling heredoc support."""
    with open(dockerfile_path, "r") as f:
        content = f.read()
    if content.startswith("# syntax="):
        return
    with open(dockerfile_path, "w") as f:
        f.write(SYNTAX_DIRECTIVE + content)


def _compute_target_image(push_dir: str, base_image: str) -> str:
    """Compute the target image name from push_dir and base_image.

    e.g. push_dir='registry.sensecore.tech/ccr-sandbox-swe', base_image='ubuntu:22.04'
    -> 'registry.sensecore.tech/ccr-sandbox-swe/ubuntu:22.04'

    If base_image has a registry prefix (contains dots in first segment), strip it.
    Preserves original path structure (multi-segment paths kept as-is).
    """
    push_dir = push_dir.rstrip("/")

    # Strip tag first
    if ":" in base_image:
        image_path, tag = base_image.rsplit(":", 1)
    else:
        image_path = base_image
        tag = "latest"

    # Remove registry prefix if present (e.g. docker.io/library/ubuntu -> library/ubuntu)
    parts = image_path.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0]):
        parts = parts[1:]

    # Preserve original path structure
    image_name = "/".join(parts)

    return f"{push_dir}/{image_name}:{tag}"


def _compute_build_image_tag(push_dir: str, base_image: str) -> str:
    """Compute a local build tag for the image (used during docker build, before final tag).

    Flattens multi-segment paths with '_' for a valid single-segment local tag.
    """
    target = _compute_target_image(push_dir, base_image)
    # Extract everything after push_dir prefix: e.g. "swebench/sweb...:latest"
    # Use the last part after the registry/repo prefix, flatten '/' to '_'
    _, _, rest = target.partition(push_dir.rstrip("/") + "/")
    if "/" in rest.rsplit(":", 1)[0]:
        # Multi-segment: flatten for local tag
        image_part, tag = rest.rsplit(":", 1)
        flat_name = image_part.replace("/", "_")
        return f"image-tools-build/{flat_name}:{tag}"
    return f"image-tools-build/{rest}"


def _compute_script_target_image(base_image: str, tag_mode: str, tag_suffix: str) -> str:
    """Compute target image for script build mode.

    The image name (registry/path) stays the same as the base image.
    Tag is computed based on tag_mode:
      - "append": old_tag + tag_suffix (e.g. "22.04" + "-custom" -> "22.04-custom")
      - "replace": tag_suffix directly (e.g. "custom")
    """
    if ":" in base_image:
        image_path, old_tag = base_image.rsplit(":", 1)
    else:
        image_path = base_image
        old_tag = "latest"

    if tag_mode == "append":
        new_tag = f"{old_tag}{tag_suffix}"
    else:
        new_tag = tag_suffix

    return f"{image_path}:{new_tag}"


def prep_shared_build_context(source_dir: str) -> str:
    """Copy OpenHands source files to a shared temp directory (once per task).

    Returns the path to the shared code directory.
    """
    shared_dir = tempfile.mkdtemp(prefix="image-tools-shared-")
    code_dir = os.path.join(shared_dir, "code")
    os.makedirs(code_dir, exist_ok=True)

    source_path = Path(source_dir)

    # Copy openhands/ directory (exclude node_modules, __pycache__, .* dirs, .pyc, .md)
    openhands_src = source_path / "openhands"
    if openhands_src.is_dir():
        shutil.copytree(
            openhands_src,
            Path(code_dir, "openhands"),
            ignore=shutil.ignore_patterns(
                ".*", "__pycache__", "*.pyc", "*.md", "node_modules",
            ),
        )

    # Copy microagents/ directory
    microagents_src = source_path / "microagents"
    if microagents_src.is_dir():
        shutil.copytree(microagents_src, Path(code_dir, "microagents"))

    # Copy pyproject.toml and poetry.lock
    for filename in ["pyproject.toml", "poetry.lock"]:
        src_file = source_path / filename
        if src_file.exists():
            shutil.copy2(src_file, Path(code_dir, filename))

    return shared_dir


class ImageBuilder:
    def __init__(self):
        self.docker_service = DockerService()
        self.dockerfile_generator = DockerfileGenerator()

    async def build_image(
        self, image_info: ImageBuildInfo, task: BuildTask, shared_build_dir: str
    ) -> None:
        """Execute the full 4-stage build pipeline for a single image."""
        image_info.status = ImageBuildStatus.BUILDING
        image_info.started_at = datetime.now()

        try:
            await self._run_with_retry(image_info, task, shared_build_dir)
        except Exception as e:
            image_info.status = ImageBuildStatus.FAILED
            image_info.error_message = str(e)
            logger.error(f"Build failed for {image_info.base_image}: {e}")
        finally:
            image_info.finished_at = datetime.now()

    async def retag_image(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        """Execute the 3-stage retag pipeline: pull → tag → push."""
        image_info.status = ImageBuildStatus.BUILDING
        image_info.started_at = datetime.now()

        try:
            await self._run_retag_with_retry(image_info, task)
        except Exception as e:
            image_info.status = ImageBuildStatus.FAILED
            image_info.error_message = str(e)
            logger.error(f"Retag failed for {image_info.base_image}: {e}")
        finally:
            image_info.finished_at = datetime.now()

    async def harbor_build_image(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        """Execute the harbor two-stage pipeline: build original → inject envd → tag → push."""
        image_info.status = ImageBuildStatus.BUILDING
        image_info.started_at = datetime.now()

        try:
            await self._run_harbor_with_retry(image_info, task)
        except Exception as e:
            image_info.status = ImageBuildStatus.FAILED
            image_info.error_message = str(e)
            logger.error(f"Harbor build failed for {image_info.base_image}: {e}")
        finally:
            image_info.finished_at = datetime.now()

    async def script_build_image(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        """Execute script build pipeline: render Dockerfile template → build → tag → push."""
        image_info.status = ImageBuildStatus.BUILDING
        image_info.started_at = datetime.now()

        try:
            await self._run_script_with_retry(image_info, task)
        except Exception as e:
            image_info.status = ImageBuildStatus.FAILED
            image_info.error_message = str(e)
            logger.error(f"Script build failed for {image_info.base_image}: {e}")
        finally:
            image_info.finished_at = datetime.now()

    async def _run_with_retry(
        self, image_info: ImageBuildInfo, task: BuildTask, shared_build_dir: str
    ) -> None:
        max_attempts = task.retry_count + 1  # retry_count=0 means 1 attempt

        for attempt in range(max_attempts):
            if attempt > 0:
                image_info.retry_attempts = attempt
                # Reset stage statuses for retry
                for stage in image_info.stages:
                    stage.status = StageStatus.PENDING
                    stage.started_at = None
                    stage.finished_at = None
                    stage.error_message = None
                logger.info(
                    f"Retry {attempt}/{task.retry_count} for {image_info.base_image}"
                )

            try:
                await self._execute_pipeline(image_info, task, shared_build_dir)
                image_info.status = ImageBuildStatus.SUCCESS
                return
            except _StageError as e:
                image_info.error_message = f"Stage [{e.stage.value}] failed: {e.message}"
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {image_info.base_image}: {e.message}"
                    )
                    continue
                else:
                    image_info.status = ImageBuildStatus.FAILED
                    logger.error(
                        f"All {max_attempts} attempts failed for {image_info.base_image}"
                    )

    async def _run_retag_with_retry(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        max_attempts = task.retry_count + 1

        for attempt in range(max_attempts):
            if attempt > 0:
                image_info.retry_attempts = attempt
                for stage in image_info.stages:
                    stage.status = StageStatus.PENDING
                    stage.started_at = None
                    stage.finished_at = None
                    stage.error_message = None
                logger.info(
                    f"Retry {attempt}/{task.retry_count} for {image_info.base_image}"
                )

            try:
                await self._execute_retag_pipeline(image_info)
                image_info.status = ImageBuildStatus.SUCCESS
                return
            except _StageError as e:
                image_info.error_message = f"Stage [{e.stage.value}] failed: {e.message}"
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {image_info.base_image}: {e.message}"
                    )
                    continue
                else:
                    image_info.status = ImageBuildStatus.FAILED
                    logger.error(
                        f"All {max_attempts} attempts failed for {image_info.base_image}"
                    )

    async def _run_harbor_with_retry(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        max_attempts = task.retry_count + 1

        for attempt in range(max_attempts):
            if attempt > 0:
                image_info.retry_attempts = attempt
                for stage in image_info.stages:
                    stage.status = StageStatus.PENDING
                    stage.started_at = None
                    stage.finished_at = None
                    stage.error_message = None
                logger.info(
                    f"Retry {attempt}/{task.retry_count} for {image_info.base_image}"
                )

            try:
                await self._execute_harbor_pipeline(image_info, task)
                image_info.status = ImageBuildStatus.SUCCESS
                return
            except _StageError as e:
                image_info.error_message = f"Stage [{e.stage.value}] failed: {e.message}"
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {image_info.base_image}: {e.message}"
                    )
                    continue
                else:
                    image_info.status = ImageBuildStatus.FAILED
                    logger.error(
                        f"All {max_attempts} attempts failed for {image_info.base_image}"
                    )

    async def _run_script_with_retry(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        max_attempts = task.retry_count + 1

        for attempt in range(max_attempts):
            if attempt > 0:
                image_info.retry_attempts = attempt
                for stage in image_info.stages:
                    stage.status = StageStatus.PENDING
                    stage.started_at = None
                    stage.finished_at = None
                    stage.error_message = None
                logger.info(
                    f"Retry {attempt}/{task.retry_count} for {image_info.base_image}"
                )

            try:
                await self._execute_script_pipeline(image_info, task)
                image_info.status = ImageBuildStatus.SUCCESS
                return
            except _StageError as e:
                image_info.error_message = f"Stage [{e.stage.value}] failed: {e.message}"
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {image_info.base_image}: {e.message}"
                    )
                    continue
                else:
                    image_info.status = ImageBuildStatus.FAILED
                    logger.error(
                        f"All {max_attempts} attempts failed for {image_info.base_image}"
                    )

    async def _execute_pipeline(
        self, image_info: ImageBuildInfo, task: BuildTask, shared_build_dir: str
    ) -> None:
        build_tag = _compute_build_image_tag(task.push_dir, image_info.base_image)
        push_succeeded = False

        # Stage 1: Generate Dockerfile into shared dir (unique name per image)
        dockerfile_path = await self._stage_generate_dockerfile(
            image_info, task, shared_build_dir
        )

        try:
            # Stage 2: Docker build (use shared dir as context, -f for Dockerfile)
            await self._stage_docker_build(
                image_info, task, shared_build_dir, build_tag, dockerfile_path
            )

            # Stage 3: Docker tag
            await self._stage_docker_tag(
                image_info, build_tag, image_info.target_image
            )

            # Stage 4: Docker push
            await self._stage_docker_push(image_info, image_info.target_image)
            push_succeeded = True
        finally:
            # Clean up per-image Dockerfile
            if dockerfile_path and os.path.exists(dockerfile_path):
                os.remove(dockerfile_path)

            # Clean up local Docker images
            await self._cleanup_images(build_tag, image_info.target_image, push_succeeded)

    async def _execute_retag_pipeline(self, image_info: ImageBuildInfo) -> None:
        """Execute pull → tag → push pipeline for retag mode."""
        push_succeeded = False

        try:
            # Stage 1: Docker pull
            await self._stage_docker_pull(image_info, image_info.base_image)

            # Stage 2: Docker tag
            await self._stage_docker_tag(
                image_info, image_info.base_image, image_info.target_image
            )

            # Stage 3: Docker push
            await self._stage_docker_push(image_info, image_info.target_image)
            push_succeeded = True
        finally:
            # Clean up target tag if push succeeded (image is in remote registry)
            if push_succeeded:
                await self.docker_service.remove_image(image_info.target_image)

    async def _execute_harbor_pipeline(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        """Execute harbor two-stage pipeline: build/pull original → inject envd → tag → push."""
        safe_name = (image_info.harbor_task_name or image_info.base_image.replace("/", "_").replace(":", "_")).lower()
        original_tag = f"image-tools-harbor/{safe_name}:original"
        envd_tag = f"image-tools-harbor/{safe_name}:envd"
        push_succeeded = False
        original_build_dir = None
        envd_build_dir = None

        try:
            # Stage 1: Build or pull original image
            stage = self._start_stage(image_info, StageName.DOCKER_BUILD_ORIGINAL)
            try:
                if image_info.harbor_docker_image:
                    # Prebuilt image: pull and tag
                    success, output = await self.docker_service.pull(image_info.harbor_docker_image)
                    if not success:
                        self._finish_stage(stage, False, output)
                        raise _StageError(StageName.DOCKER_BUILD_ORIGINAL, output)
                    success, output = await self.docker_service.tag(image_info.harbor_docker_image, original_tag)
                    if not success:
                        self._finish_stage(stage, False, output)
                        raise _StageError(StageName.DOCKER_BUILD_ORIGINAL, output)
                elif image_info.harbor_dockerfile_path:
                    # Copy build context to tempdir to avoid modifying the original dataset files.
                    # _ensure_syntax_directive writes to the Dockerfile, which would change
                    # dirhash(environment/) and break template_name on subsequent retry tasks.
                    src_context = os.path.dirname(image_info.harbor_dockerfile_path)
                    original_build_dir = tempfile.mkdtemp(prefix="image-tools-harbor-orig-")
                    build_context = os.path.join(original_build_dir, "context")
                    shutil.copytree(src_context, build_context)
                    copied_dockerfile = os.path.join(
                        build_context, os.path.basename(image_info.harbor_dockerfile_path)
                    )
                    _ensure_syntax_directive(copied_dockerfile)
                    success, output, _ = await self.docker_service.build(
                        build_context_path=build_context,
                        tags=[original_tag],
                        build_args=["--network=host"],
                    )
                    if not success:
                        error_lines = [l for l in output.split("\n") if l.strip() and "ERROR" in l.upper()]
                        error_msg = "\n".join(error_lines[-5:]) if error_lines else output[-2000:]
                        self._finish_stage(stage, False, error_msg)
                        raise _StageError(StageName.DOCKER_BUILD_ORIGINAL, error_msg)
                else:
                    # Fallback: pull base_image directly
                    success, output = await self.docker_service.pull(image_info.base_image)
                    if not success:
                        self._finish_stage(stage, False, output)
                        raise _StageError(StageName.DOCKER_BUILD_ORIGINAL, output)
                    success, output = await self.docker_service.tag(image_info.base_image, original_tag)
                    if not success:
                        self._finish_stage(stage, False, output)
                        raise _StageError(StageName.DOCKER_BUILD_ORIGINAL, output)

                self._finish_stage(stage, True)
            except _StageError:
                raise
            except Exception as e:
                self._finish_stage(stage, False, str(e))
                raise _StageError(StageName.DOCKER_BUILD_ORIGINAL, str(e))

            # Stage 2: Build envd injection layer on top of original
            stage = self._start_stage(image_info, StageName.DOCKER_BUILD_ENVD)
            try:
                envd_build_dir = tempfile.mkdtemp(prefix="image-tools-envd-")

                # Copy envd binary
                envd_src = task.envd_binary_path
                if not envd_src or not os.path.isfile(envd_src):
                    raise FileNotFoundError(f"envd binary not found: {envd_src}")
                shutil.copy2(envd_src, os.path.join(envd_build_dir, "envd"))

                # Write entrypoint.sh
                entrypoint_content = (
                    "#!/bin/sh\n"
                    "set -e\n"
                    "\n"
                    "# Start envd (e2b infra daemon) in background\n"
                    "envd -port 49983 -isnotfc &\n"
                    "\n"
                    '# Execute the passed command, or default to sh\n'
                    'exec "${@:-sh}"\n'
                )
                with open(os.path.join(envd_build_dir, "entrypoint.sh"), "w") as f:
                    f.write(entrypoint_content)

                # Generate Dockerfile from template
                dockerfile_content = self.dockerfile_generator.generate_envd(original_tag)
                with open(os.path.join(envd_build_dir, "Dockerfile"), "w") as f:
                    f.write(dockerfile_content)

                # Build
                success, output, _ = await self.docker_service.build(
                    build_context_path=envd_build_dir,
                    tags=[envd_tag],
                    build_args=["--network=host"],
                )
                if not success:
                    error_lines = [l for l in output.split("\n") if l.strip() and "ERROR" in l.upper()]
                    error_msg = "\n".join(error_lines[-5:]) if error_lines else output[-2000:]
                    self._finish_stage(stage, False, error_msg)
                    raise _StageError(StageName.DOCKER_BUILD_ENVD, error_msg)

                self._finish_stage(stage, True)
            except _StageError:
                raise
            except Exception as e:
                self._finish_stage(stage, False, str(e))
                raise _StageError(StageName.DOCKER_BUILD_ENVD, str(e))

            # Stage 3: Docker tag
            await self._stage_docker_tag(image_info, envd_tag, image_info.target_image)

            # Stage 4: Docker push
            await self._stage_docker_push(image_info, image_info.target_image)
            push_succeeded = True
        finally:
            # Clean up temp dirs
            if original_build_dir:
                shutil.rmtree(original_build_dir, ignore_errors=True)
            if envd_build_dir:
                shutil.rmtree(envd_build_dir, ignore_errors=True)
            # Clean up local Docker images
            await self.docker_service.remove_image(original_tag)
            await self.docker_service.remove_image(envd_tag)
            if push_succeeded:
                await self.docker_service.remove_image(image_info.target_image)

    async def _execute_script_pipeline(
        self, image_info: ImageBuildInfo, task: BuildTask
    ) -> None:
        """Execute script build pipeline: render Dockerfile → build → tag → push."""
        safe_name = image_info.base_image.replace("/", "_").replace(":", "_").lower()
        build_tag = f"image-tools-script/{safe_name}:build"
        push_succeeded = False
        build_dir = None

        try:
            # Stage 1: Docker build from rendered Dockerfile template
            stage = self._start_stage(image_info, StageName.DOCKER_BUILD)
            try:
                build_dir = tempfile.mkdtemp(prefix="image-tools-script-")

                # Render Dockerfile by replacing placeholder with actual base image
                rendered = task.dockerfile_content.replace(
                    SCRIPT_BASE_IMAGE_PLACEHOLDER, image_info.base_image
                )
                dockerfile_path = os.path.join(build_dir, "Dockerfile")
                with open(dockerfile_path, "w") as f:
                    f.write(rendered)

                success, output, _ = await self.docker_service.build(
                    build_context_path=build_dir,
                    tags=[build_tag],
                    build_args=task.build_args if task.build_args else None,
                )
                if not success:
                    error_lines = [l for l in output.split("\n") if l.strip() and "ERROR" in l.upper()]
                    error_msg = "\n".join(error_lines[-5:]) if error_lines else output[-2000:]
                    self._finish_stage(stage, False, error_msg)
                    raise _StageError(StageName.DOCKER_BUILD, error_msg)

                self._finish_stage(stage, True)
            except _StageError:
                raise
            except Exception as e:
                self._finish_stage(stage, False, str(e))
                raise _StageError(StageName.DOCKER_BUILD, str(e))

            # Stage 2: Docker tag
            await self._stage_docker_tag(image_info, build_tag, image_info.target_image)

            # Stage 3: Docker push
            await self._stage_docker_push(image_info, image_info.target_image)
            push_succeeded = True
        finally:
            # Clean up temp dir
            if build_dir:
                shutil.rmtree(build_dir, ignore_errors=True)
            # Clean up local Docker images
            await self.docker_service.remove_image(build_tag)
            if push_succeeded:
                await self.docker_service.remove_image(image_info.target_image)

    async def _cleanup_images(
        self, build_tag: str, target_image: str, push_succeeded: bool
    ) -> None:
        """Remove temporary local Docker images after build.

        - Always remove the build tag (image-tools-build/...)
        - Remove target tag only if push succeeded (already in remote registry)
        """
        # Always remove build tag
        await self.docker_service.remove_image(build_tag)

        # Remove target tag if push succeeded (image is in the remote registry)
        if push_succeeded:
            await self.docker_service.remove_image(target_image)


    def _get_stage(self, image_info: ImageBuildInfo, stage_name: StageName):
        for stage in image_info.stages:
            if stage.name == stage_name:
                return stage
        raise ValueError(f"Stage {stage_name} not found")

    def _start_stage(self, image_info: ImageBuildInfo, stage_name: StageName):
        stage = self._get_stage(image_info, stage_name)
        stage.status = StageStatus.RUNNING
        stage.started_at = datetime.now()
        return stage

    def _finish_stage(self, stage, success: bool, error_message: str | None = None):
        stage.finished_at = datetime.now()
        if success:
            stage.status = StageStatus.SUCCESS
        else:
            stage.status = StageStatus.FAILED
            stage.error_message = error_message

    async def _stage_docker_pull(
        self, image_info: ImageBuildInfo, image: str
    ) -> None:
        stage = self._start_stage(image_info, StageName.DOCKER_PULL)

        try:
            success, output = await self.docker_service.pull(image)
            if not success:
                self._finish_stage(stage, False, output)
                raise _StageError(StageName.DOCKER_PULL, output)
            self._finish_stage(stage, True)

        except _StageError:
            raise
        except Exception as e:
            self._finish_stage(stage, False, str(e))
            raise _StageError(StageName.DOCKER_PULL, str(e))

    async def _stage_generate_dockerfile(
        self, image_info: ImageBuildInfo, task: BuildTask, shared_build_dir: str
    ) -> str:
        """Generate Dockerfile into shared build dir with a unique name per image."""
        stage = self._start_stage(image_info, StageName.GENERATE_DOCKERFILE)

        try:
            dockerfile_content = self.dockerfile_generator.generate(
                base_image=image_info.base_image,
                deps_image=task.deps_image,
            )

            # Use unique Dockerfile name to support parallel builds
            safe_name = image_info.base_image.replace("/", "_").replace(":", "_")
            dockerfile_path = os.path.join(
                shared_build_dir, f"Dockerfile.{safe_name}"
            )

            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)

            self._finish_stage(stage, True)
            return dockerfile_path

        except Exception as e:
            self._finish_stage(stage, False, str(e))
            raise _StageError(StageName.GENERATE_DOCKERFILE, str(e))

    async def _stage_docker_build(
        self,
        image_info: ImageBuildInfo,
        task: BuildTask,
        build_dir: str,
        build_tag: str,
        dockerfile_path: str | None = None,
    ) -> None:
        stage = self._start_stage(image_info, StageName.DOCKER_BUILD)

        try:
            success, output, _ = await self.docker_service.build(
                build_context_path=build_dir,
                tags=[build_tag],
                build_args=task.build_args if task.build_args else None,
                dockerfile_path=dockerfile_path,
            )

            if not success:
                # Extract last meaningful error lines
                error_lines = [
                    l for l in output.split("\n") if l.strip() and "ERROR" in l.upper()
                ]
                error_msg = "\n".join(error_lines[-5:]) if error_lines else output[-2000:]
                self._finish_stage(stage, False, error_msg)
                raise _StageError(StageName.DOCKER_BUILD, error_msg)

            self._finish_stage(stage, True)

        except _StageError:
            raise
        except Exception as e:
            self._finish_stage(stage, False, str(e))
            raise _StageError(StageName.DOCKER_BUILD, str(e))

    async def _stage_docker_tag(
        self, image_info: ImageBuildInfo, source_tag: str, target_image: str
    ) -> None:
        stage = self._start_stage(image_info, StageName.DOCKER_TAG)

        try:
            success, output = await self.docker_service.tag(source_tag, target_image)
            if not success:
                self._finish_stage(stage, False, output)
                raise _StageError(StageName.DOCKER_TAG, output)
            self._finish_stage(stage, True)

        except _StageError:
            raise
        except Exception as e:
            self._finish_stage(stage, False, str(e))
            raise _StageError(StageName.DOCKER_TAG, str(e))

    async def _stage_docker_push(
        self, image_info: ImageBuildInfo, target_image: str
    ) -> None:
        stage = self._start_stage(image_info, StageName.DOCKER_PUSH)

        try:
            success, output = await self.docker_service.push(target_image)
            if not success:
                self._finish_stage(stage, False, output)
                raise _StageError(StageName.DOCKER_PUSH, output)
            self._finish_stage(stage, True)

        except _StageError:
            raise
        except Exception as e:
            self._finish_stage(stage, False, str(e))
            raise _StageError(StageName.DOCKER_PUSH, str(e))


class _StageError(Exception):
    def __init__(self, stage: StageName, message: str):
        self.stage = stage
        self.message = message
        super().__init__(f"[{stage.value}] {message}")
