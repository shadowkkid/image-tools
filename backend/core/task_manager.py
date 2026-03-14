import asyncio
import logging
from datetime import datetime

from backend.builder.image_builder import ImageBuilder, _compute_target_image
from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    TaskStatus,
)

logger = logging.getLogger(__name__)

# Default OpenHands source directory
DEFAULT_SOURCE_DIR = "/home/SENSETIME/lizimu/workspace/python/OpenHands_Ss"


class TaskManager:
    def __init__(self):
        self.tasks: dict[str, BuildTask] = {}
        self.image_builder = ImageBuilder()
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        task_name: str,
        deps_image: str,
        base_images: list[str],
        push_dir: str,
        build_args: list[str] | None = None,
        retry_count: int = 0,
        source_dir: str | None = None,
    ) -> BuildTask:
        """Create a new build task and start execution in background."""
        task = BuildTask(
            task_name=task_name,
            deps_image=deps_image,
            push_dir=push_dir,
            base_images=base_images,
            build_args=build_args or [],
            retry_count=retry_count,
            source_dir=source_dir or DEFAULT_SOURCE_DIR,
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

        # Start background execution
        asyncio.create_task(self._execute_task(task))

        return task

    async def _execute_task(self, task: BuildTask) -> None:
        """Execute all image builds sequentially for a task."""
        task.status = TaskStatus.RUNNING

        for image_info in task.images:
            try:
                await self.image_builder.build_image(image_info, task)
            except Exception as e:
                logger.error(f"Unexpected error building {image_info.base_image}: {e}")

        # Determine final task status
        task.finished_at = datetime.now()

        if task.failed_images == 0:
            task.status = TaskStatus.COMPLETED
        elif task.completed_images == 0:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.PARTIAL_FAILED

        logger.info(
            f"Task [{task.task_name}] finished: {task.status.value} "
            f"({task.completed_images}/{task.total_images} succeeded)"
        )

    def get_task(self, task_id: str) -> BuildTask | None:
        return self.tasks.get(task_id)

    def list_tasks(self) -> list[BuildTask]:
        return list(self.tasks.values())


# Global instance
task_manager = TaskManager()
