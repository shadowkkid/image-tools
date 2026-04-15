import asyncio
import logging
import shutil
from datetime import datetime

from backend.builder.image_builder import (
    ImageBuilder,
    _compute_build_image_tag,
    _compute_script_target_image,
    _compute_target_image,
    prep_shared_build_context,
)
from backend.config import get_agent_config
from backend.core.database import add_dataset_image, delete_task as db_delete_task, ensure_dataset, init_db, load_all_tasks, save_task
from backend.core.docker_service import DockerService
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    HARBOR_STAGES,
    RETAG_STAGES,
    SCRIPT_BUILD_STAGES,
    StageStatus,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = init_db(db_path)
        self.tasks: dict[str, BuildTask] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}
        self.image_builder = ImageBuilder()
        self._lock = asyncio.Lock()
        self._image_refs: dict[str, int] = {}
        self._refs_lock = asyncio.Lock()

        # Restore tasks from DB
        self._restore_tasks()

    def _restore_tasks(self) -> None:
        """Load tasks from DB and reconcile interrupted running tasks."""
        self.tasks = load_all_tasks(self.db_path)
        for task in self.tasks.values():
            if task.status != TaskStatus.RUNNING:
                continue

            logger.warning(
                f"Task [{task.task_name}] was running when server stopped, reconciling..."
            )
            recovered = 0
            for img in task.images:
                if img.status == ImageBuildStatus.BUILDING:
                    # Check if the image actually made it to the registry
                    if DockerService.manifest_exists(img.target_image):
                        img.status = ImageBuildStatus.SUCCESS
                        img.error_message = None
                        img.finished_at = img.finished_at or datetime.now()
                        for stage in img.stages:
                            if stage.status != StageStatus.SUCCESS:
                                stage.status = StageStatus.SUCCESS
                                stage.finished_at = stage.finished_at or datetime.now()
                        recovered += 1
                        logger.info(
                            f"  Recovered {img.base_image} (exists in registry)"
                        )
                    else:
                        img.status = ImageBuildStatus.FAILED
                        img.error_message = "Server restarted while task was running"
                        img.finished_at = img.finished_at or datetime.now()
                elif img.status == ImageBuildStatus.PENDING:
                    img.status = ImageBuildStatus.FAILED
                    img.error_message = "Server restarted while task was running"
                    img.finished_at = img.finished_at or datetime.now()

            # Compute correct task status based on actual results
            task.finished_at = task.finished_at or datetime.now()
            if task.failed_images == 0:
                task.status = TaskStatus.COMPLETED
            elif task.completed_images == 0:
                task.status = TaskStatus.FAILED
            else:
                task.status = TaskStatus.PARTIAL_FAILED

            if recovered:
                logger.info(
                    f"  Task [{task.task_name}] recovered {recovered} images from registry"
                )
            logger.info(
                f"  Task [{task.task_name}] final: {task.status.value} "
                f"({task.completed_images}/{task.total_images} succeeded)"
            )
            save_task(task, self.db_path)
        logger.info(f"Restored {len(self.tasks)} tasks from database")

        # Back-fill missing dataset_images for completed successful images
        for task in self.tasks.values():
            if not task.dataset:
                continue
            for img in task.images:
                if img.status == ImageBuildStatus.SUCCESS:
                    self._record_dataset_image(task, img)

    def _save(self, task: BuildTask) -> None:
        """Persist task state to DB."""
        try:
            save_task(task, self.db_path)
        except Exception as e:
            logger.error(f"Failed to save task [{task.task_name}] to DB: {e}")

    async def create_task(
        self,
        task_name: str,
        agent: str,
        agent_version: str,
        dataset: str,
        base_images: list[str],
        push_dir: str,
        build_args: list[str] | None = None,
        retry_count: int = 0,
        concurrency: int = 2,
        dataset_path: str = "",
        harbor_task_names: list[str] | None = None,
        build_type: str = "opensource",
        dockerfile_content: str = "",
        tag_mode: str = "",
        tag_suffix: str = "",
    ) -> BuildTask:
        """Create a new build task and start execution in background."""
        if build_type == "script":
            return await self._create_script_task(
                task_name=task_name,
                base_images=base_images,
                dockerfile_content=dockerfile_content,
                tag_mode=tag_mode,
                tag_suffix=tag_suffix,
                build_args=build_args,
                retry_count=retry_count,
                concurrency=concurrency,
            )

        # Resolve agent config
        agent_cfg = get_agent_config(agent, agent_version)
        deps_image = agent_cfg.get("deps_image", "")
        source_dir = agent_cfg.get("source_dir", "")
        build_mode = agent_cfg.get("build_mode", "build")
        envd_binary_path = agent_cfg.get("envd_binary_path", "")

        # Ensure dataset exists
        ensure_dataset(dataset, agent, agent_version, self.db_path)

        if build_mode == "harbor":
            # Harbor mode: parse dataset to get task environments
            from backend.builder.harbor_dataset_parser import (
                compute_template_name,
                extract_dataset_name,
                resolve_and_parse,
            )

            if not dataset_path:
                raise ValueError("Harbor agent requires a dataset_path (local path or dataset@version)")

            local_path, harbor_tasks = resolve_and_parse(dataset_path)
            ds_name = extract_dataset_name(local_path)

            # Filter by harbor_task_names if specified (retry failed images only)
            if harbor_task_names:
                names_set = set(harbor_task_names)
                harbor_tasks = [ht for ht in harbor_tasks if ht.task_name in names_set]
            elif base_images:
                base_images_set = set(base_images)
                harbor_tasks = [ht for ht in harbor_tasks if ht.base_image in base_images_set]

            task = BuildTask(
                task_name=task_name,
                deps_image="",
                push_dir=push_dir,
                base_images=[ht.base_image for ht in harbor_tasks],
                agent=agent,
                agent_version=agent_version,
                dataset=dataset,
                build_args=build_args or [],
                retry_count=retry_count,
                source_dir="",
                build_mode=build_mode,
                dataset_path=local_path,
                envd_binary_path=envd_binary_path,
                concurrency=max(1, concurrency),
            )

            for ht in harbor_tasks:
                tmpl_name = compute_template_name(ds_name, ht.task_name, ht.task_dir)
                target_image = f"{push_dir.rstrip('/')}/{tmpl_name}:latest".lower()
                task.images.append(
                    ImageBuildInfo(
                        base_image=ht.base_image,
                        target_image=target_image,
                        template_name=tmpl_name,
                        harbor_task_name=ht.task_name,
                        harbor_dockerfile_path=ht.dockerfile_path,
                        harbor_docker_image=ht.docker_image,
                        stage_names=HARBOR_STAGES,
                    )
                )
        else:
            task = BuildTask(
                task_name=task_name,
                deps_image=deps_image,
                push_dir=push_dir,
                base_images=base_images,
                agent=agent,
                agent_version=agent_version,
                dataset=dataset,
                build_args=build_args or [],
                retry_count=retry_count,
                source_dir=source_dir,
                build_mode=build_mode,
                concurrency=max(1, concurrency),
            )

            # Create ImageBuildInfo for each base image
            stage_names = RETAG_STAGES if build_mode == "retag" else []
            for base_image in base_images:
                target_image = _compute_target_image(push_dir, base_image)
                task.images.append(
                    ImageBuildInfo(
                        base_image=base_image,
                        target_image=target_image,
                        stage_names=stage_names,
                    )
                )

        async with self._lock:
            self.tasks[task.task_id] = task

        # Save to DB after creation
        self._save(task)

        # Start background execution
        bg_task = asyncio.create_task(self._execute_task(task))
        self._async_tasks[task.task_id] = bg_task

        return task

    async def _create_script_task(
        self,
        task_name: str,
        base_images: list[str],
        dockerfile_content: str,
        tag_mode: str,
        tag_suffix: str,
        build_args: list[str] | None = None,
        retry_count: int = 0,
        concurrency: int = 2,
    ) -> BuildTask:
        """Create a script-based build task."""
        task = BuildTask(
            task_name=task_name,
            deps_image="",
            push_dir="",
            base_images=base_images,
            agent="",
            agent_version="",
            dataset="",
            build_args=build_args or [],
            retry_count=retry_count,
            build_mode="script",
            dockerfile_content=dockerfile_content,
            tag_mode=tag_mode,
            tag_suffix=tag_suffix,
            concurrency=max(1, concurrency),
        )

        for base_image in base_images:
            target_image = _compute_script_target_image(base_image, tag_mode, tag_suffix)
            task.images.append(
                ImageBuildInfo(
                    base_image=base_image,
                    target_image=target_image,
                    stage_names=SCRIPT_BUILD_STAGES,
                )
            )

        async with self._lock:
            self.tasks[task.task_id] = task

        self._save(task)

        bg_task = asyncio.create_task(self._execute_task(task))
        self._async_tasks[task.task_id] = bg_task

        return task

    @staticmethod
    def _get_task_images(task: BuildTask) -> set[str]:
        """Return the set of base images used by a task.

        deps_image is excluded — it's large, slow to pull, and shared across
        tasks, so we deliberately keep it cached on disk.
        """
        return set(task.base_images)

    async def _register_task_images(self, task: BuildTask) -> None:
        """Increment reference count for each image used by the task."""
        async with self._refs_lock:
            for image in self._get_task_images(task):
                self._image_refs[image] = self._image_refs.get(image, 0) + 1

    async def _unregister_task_images(self, task: BuildTask) -> list[str]:
        """Decrement reference count; return images whose count reached zero."""
        to_remove: list[str] = []
        async with self._refs_lock:
            for image in self._get_task_images(task):
                count = self._image_refs.get(image, 0) - 1
                if count <= 0:
                    self._image_refs.pop(image, None)
                    to_remove.append(image)
                else:
                    self._image_refs[image] = count
        return to_remove

    async def _cleanup_task_images(self, task: BuildTask) -> None:
        """Unregister task images and remove those no longer referenced."""
        to_remove = await self._unregister_task_images(task)
        for image in to_remove:
            try:
                await DockerService.remove_image(image)
            except Exception as e:
                logger.debug(f"Failed to remove image {image}: {e}")
        try:
            await DockerService.prune_images()
        except Exception as e:
            logger.debug(f"Failed to prune images: {e}")

    async def _cleanup_build_images(self, task: BuildTask) -> None:
        """Remove build tags and target tags for all images in a cancelled task."""
        for img in task.images:
            build_tag = _compute_build_image_tag(task.push_dir, img.base_image)
            try:
                await DockerService.remove_image(build_tag)
            except Exception as e:
                logger.debug(f"Failed to remove build tag {build_tag}: {e}")
            # Only remove target tag if it wasn't pushed
            if img.status != ImageBuildStatus.SUCCESS:
                try:
                    await DockerService.remove_image(img.target_image)
                except Exception as e:
                    logger.debug(f"Failed to remove target tag {img.target_image}: {e}")
        try:
            await DockerService.prune_images()
        except Exception as e:
            logger.debug(f"Failed to prune images: {e}")

    async def _execute_task(self, task: BuildTask) -> None:
        """Execute all image builds with configurable concurrency."""
        task.status = TaskStatus.RUNNING
        self._save(task)
        await self._register_task_images(task)
        shared_build_dir = None

        try:
            # Prepare shared build context only for full build mode
            if task.build_mode == "build":
                logger.info(f"Task [{task.task_name}] preparing shared build context...")
                shared_build_dir = await asyncio.get_event_loop().run_in_executor(
                    None, prep_shared_build_context, task.source_dir
                )
                logger.info(f"Task [{task.task_name}] shared build context ready")
            else:
                logger.info(f"Task [{task.task_name}] {task.build_mode} mode, skipping build context")

            prune_counter = 0
            prune_lock = asyncio.Lock()
            PRUNE_EVERY_N = 50

            async def _maybe_prune():
                nonlocal prune_counter
                async with prune_lock:
                    prune_counter += 1
                    if prune_counter % PRUNE_EVERY_N != 0:
                        return
                try:
                    await DockerService.prune_images()
                except Exception as e:
                    logger.debug(f"Periodic prune_images failed: {e}")
                if task.build_mode in ("build", "harbor", "script"):
                    try:
                        await DockerService.prune_build_cache()
                    except Exception as e:
                        logger.debug(f"Periodic prune_build_cache failed: {e}")

            async def process_image(img: ImageBuildInfo):
                try:
                    if task.build_mode == "retag":
                        await self.image_builder.retag_image(img, task)
                    elif task.build_mode == "harbor":
                        await self.image_builder.harbor_build_image(img, task)
                    elif task.build_mode == "script":
                        await self.image_builder.script_build_image(img, task)
                    else:
                        await self.image_builder.build_image(
                            img, task, shared_build_dir
                        )
                except Exception as e:
                    logger.error(
                        f"Unexpected error processing {img.base_image}: {e}"
                    )
                finally:
                    self._save(task)
                    self._record_dataset_image(task, img)
                    await _maybe_prune()

            if task.concurrency <= 1:
                for image_info in task.images:
                    await process_image(image_info)
            else:
                sem = asyncio.Semaphore(task.concurrency)

                async def build_with_limit(img: ImageBuildInfo):
                    async with sem:
                        await process_image(img)

                await asyncio.gather(
                    *(build_with_limit(img) for img in task.images)
                )

        except asyncio.CancelledError:
            logger.info(f"Task [{task.task_name}] was cancelled")
            task.status = TaskStatus.CANCELLED
            # Mark pending/building images as cancelled
            for img in task.images:
                if img.status in (ImageBuildStatus.PENDING, ImageBuildStatus.BUILDING):
                    img.status = ImageBuildStatus.CANCELLED
            task.finished_at = datetime.now()
            self._save(task)
            # Clean up build/target images that may have been created
            # Use shield to prevent this cleanup from being cancelled
            try:
                await asyncio.shield(self._cleanup_build_images(task))
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Build image cleanup on cancel failed: {e}")
            return
        except Exception as e:
            logger.error(f"Task [{task.task_name}] failed to prepare build context: {e}")
            task.status = TaskStatus.FAILED
            task.finished_at = datetime.now()
            self._save(task)
            return
        finally:
            # Clean up shared build context
            if shared_build_dir:
                shutil.rmtree(shared_build_dir, ignore_errors=True)
            # Remove asyncio task reference
            self._async_tasks.pop(task.task_id, None)
            # Unregister images and remove unreferenced ones
            try:
                await self._cleanup_task_images(task)
            except Exception as e:
                logger.warning(f"Image cleanup failed: {e}")
            # Prune BuildKit cache once per task (not per image) to avoid
            # destroying shared apt/layer caches during concurrent builds.
            if task.build_mode in ("build", "harbor", "script"):
                try:
                    await DockerService.prune_build_cache()
                except Exception as e:
                    logger.warning(f"Build cache prune failed: {e}")

        # Determine final task status
        task.finished_at = datetime.now()

        if task.failed_images == 0:
            task.status = TaskStatus.COMPLETED
        elif task.completed_images == 0:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.PARTIAL_FAILED

        self._save(task)

        logger.info(
            f"Task [{task.task_name}] finished: {task.status.value} "
            f"({task.completed_images}/{task.total_images} succeeded)"
        )

    def _record_dataset_image(self, task: BuildTask, img: ImageBuildInfo) -> None:
        """Record successfully pushed image into its dataset."""
        if img.status == ImageBuildStatus.SUCCESS and task.dataset:
            try:
                add_dataset_image(
                    task.dataset, img.target_image, task.task_id,
                    task.agent, task.agent_version, self.db_path,
                )
            except Exception as e:
                logger.error(f"Failed to record dataset image: {e}")

    def get_task(self, task_id: str) -> BuildTask | None:
        return self.tasks.get(task_id)

    def list_tasks(self) -> list[BuildTask]:
        return list(self.tasks.values())

    async def stop_task(self, task_id: str) -> tuple[bool, str]:
        """Stop a running task by cancelling its asyncio task."""
        task = self.tasks.get(task_id)
        if not task:
            return False, "任务不存在"
        if task.status != TaskStatus.RUNNING:
            return False, f"任务当前状态为 {task.status.value}，无法停止"

        bg_task = self._async_tasks.get(task_id)
        if bg_task and not bg_task.done():
            bg_task.cancel()
            return True, "任务正在停止"

        return False, "未找到运行中的后台任务"

    async def delete_task(self, task_id: str) -> tuple[bool, str]:
        """Delete a finished task from memory and DB."""
        task = self.tasks.get(task_id)
        if not task:
            return False, "任务不存在"
        if task.status == TaskStatus.RUNNING:
            return False, "运行中的任务无法删除，请先停止任务"

        async with self._lock:
            self.tasks.pop(task_id, None)
        self._async_tasks.pop(task_id, None)
        db_delete_task(task_id, self.db_path)
        return True, "任务已删除"


# Global instance
task_manager = TaskManager()
