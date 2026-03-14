from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    CreateTaskRequest,
    ImageDetail,
    StageDetail,
    TaskDetail,
    TaskListResponse,
    TaskSummary,
)
from backend.core.task_manager import task_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskSummary, status_code=201)
async def create_task(req: CreateTaskRequest):
    task = await task_manager.create_task(
        task_name=req.task_name,
        deps_image=req.deps_image,
        base_images=req.base_images,
        push_dir=req.push_dir,
        build_args=req.build_args,
        retry_count=req.retry_count,
        source_dir=req.source_dir,
    )
    return _to_summary(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks():
    tasks = task_manager.list_tasks()
    return TaskListResponse(
        tasks=[_to_summary(t) for t in tasks]
    )


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskDetail(
        task_id=task.task_id,
        task_name=task.task_name,
        status=task.status.value,
        deps_image=task.deps_image,
        push_dir=task.push_dir,
        build_args=task.build_args,
        retry_count=task.retry_count,
        source_dir=task.source_dir,
        created_at=task.created_at.isoformat(),
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
        elapsed_seconds=task.elapsed_seconds,
        total_images=task.total_images,
        completed_images=task.completed_images,
        failed_images=task.failed_images,
        images=[_to_image_detail(img) for img in task.images],
    )


def _to_summary(task) -> TaskSummary:
    return TaskSummary(
        task_id=task.task_id,
        task_name=task.task_name,
        status=task.status.value,
        total_images=task.total_images,
        completed_images=task.completed_images,
        failed_images=task.failed_images,
        created_at=task.created_at.isoformat(),
        elapsed_seconds=task.elapsed_seconds,
    )


def _to_image_detail(img) -> ImageDetail:
    return ImageDetail(
        base_image=img.base_image,
        target_image=img.target_image,
        status=img.status.value,
        current_stage=img.current_stage,
        elapsed_seconds=img.elapsed_seconds,
        retry_attempts=img.retry_attempts,
        error_message=img.error_message,
        stages=[
            StageDetail(
                name=s.name.value,
                status=s.status.value,
                elapsed_seconds=s.elapsed_seconds,
                error_message=s.error_message,
            )
            for s in img.stages
        ],
    )
