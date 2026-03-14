import asyncio
import logging
import os
import shutil
from datetime import datetime

from backend.builder.image_builder import (
    ImageBuilder,
    _compute_build_image_tag,
    _compute_target_image,
    prep_shared_build_context,
)
from backend.core.database import init_db, load_all_tasks, save_task
from backend.core.docker_service import DockerService
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    TaskStatus,
)

logger = logging.getLogger(__name__)

# Default OpenHands source directory (configurable via environment variable)
DEFAULT_SOURCE_DIR = os.environ.get(
    "IMAGE_TOOLS_SOURCE_DIR",
    "/home/SENSETIME/lizimu/workspace/python/OpenHands_Ss",
)


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
        """Load tasks from DB and mark interrupted running tasks as failed."""
        self.tasks = load_all_tasks(self.db_path)
        for task in self.tasks.values():
            if task.status == TaskStatus.RUNNING:
                logger.warning(
                    f"Task [{task.task_name}] was running when server stopped, marking as failed"
                )
                task.status = TaskStatus.FAILED
                task.finished_at = task.finished_at or datetime.now()
                for img in task.images:
                    if img.status in (ImageBuildStatus.PENDING, ImageBuildStatus.BUILDING):
                        img.status = ImageBuildStatus.FAILED
                        img.error_message = "Server restarted while task was running"
                        img.finished_at = img.finished_at or datetime.now()
                save_task(task, self.db_path)
        logger.info(f"Restored {len(self.tasks)} tasks from database")

    def _save(self, task: BuildTask) -> None:
        """Persist task state to DB."""
        try:
            save_task(task, self.db_path)
        except Exception as e:
            logger.error(f"Failed to save task [{task.task_name}] to DB: {e}")

    async def create_task(
        self,
        task_name: str,
        deps_image: str,
        base_images: list[str],
        push_dir: str,
        build_args: list[str] | None = None,
        retry_count: int = 0,
        concurrency: int = 2,
    ) -> BuildTask:
        """Create a new build task and start execution in background."""
        task = BuildTask(
            task_name=task_name,
            deps_image=deps_image,
            push_dir=push_dir,
            base_images=base_images,
            build_args=build_args or [],
            retry_count=retry_count,
            source_dir=DEFAULT_SOURCE_DIR,
            concurrency=max(1, concurrency),
        )

        # Create ImageBuildInfo for each base image
        for base_image in base_images:
            target_image = _compute_target_image(push_dir, base_image)
            task.images.append(
                ImageBuildInfo(
                    base_image=base_image,
                    target_image=target_image,
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
            # Prepare shared build context once for all images
            logger.info(f"Task [{task.task_name}] preparing shared build context...")
            shared_build_dir = await asyncio.get_event_loop().run_in_executor(
                None, prep_shared_build_context, task.source_dir
            )
            logger.info(f"Task [{task.task_name}] shared build context ready")

            if task.concurrency <= 1:
                # Sequential execution
                for image_info in task.images:
                    try:
                        await self.image_builder.build_image(
                            image_info, task, shared_build_dir
                        )
                    except Exception as e:
                        logger.error(
                            f"Unexpected error building {image_info.base_image}: {e}"
                        )
                    finally:
                        self._save(task)
            else:
                # Parallel execution with semaphore
                sem = asyncio.Semaphore(task.concurrency)

                async def build_with_limit(img: ImageBuildInfo):
                    async with sem:
                        try:
                            await self.image_builder.build_image(
                                img, task, shared_build_dir
                            )
                        except Exception as e:
                            logger.error(
                                f"Unexpected error building {img.base_image}: {e}"
                            )
                        finally:
                            self._save(task)

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


# Global instance
task_manager = TaskManager()
