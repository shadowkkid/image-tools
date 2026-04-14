from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    CreateTaskRequest,
    ExportFailedImagesResponse,
    ImageDetail,
    StageDetail,
    TaskDetail,
    TaskListResponse,
    TaskSummary,
)
from backend.core.task_manager import task_manager
from backend.core.task_models import ImageBuildStatus

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskSummary, status_code=201)
async def create_task(req: CreateTaskRequest):
    try:
        task = await task_manager.create_task(
            task_name=req.task_name,
            agent=req.agent,
            agent_version=req.agent_version,
            dataset=req.dataset,
            base_images=req.base_images,
            push_dir=req.push_dir,
            build_args=req.build_args,
            retry_count=req.retry_count,
            concurrency=req.concurrency,
            dataset_path=req.dataset_path,
            harbor_task_names=req.harbor_task_names,
            build_type=req.build_type,
            dockerfile_content=req.dockerfile_content,
            tag_mode=req.tag_mode,
            tag_suffix=req.tag_suffix,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_summary(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks():
    tasks = task_manager.list_tasks()
    return TaskListResponse(
        tasks=[_to_summary(t) for t in tasks]
    )


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: str,
    image_page: int = Query(1, ge=1),
    image_page_size: int = Query(500, ge=1, le=2000),
):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    start = (image_page - 1) * image_page_size
    end = start + image_page_size
    paginated_images = task.images[start:end]

    return TaskDetail(
        task_id=task.task_id,
        task_name=task.task_name,
        agent=task.agent,
        agent_version=task.agent_version,
        dataset=task.dataset,
        status=task.status.value,
        build_mode=task.build_mode,
        deps_image=task.deps_image,
        push_dir=task.push_dir,
        build_args=task.build_args,
        retry_count=task.retry_count,
        concurrency=task.concurrency,
        dataset_path=task.dataset_path,
        dockerfile_content=task.dockerfile_content,
        tag_mode=task.tag_mode,
        tag_suffix=task.tag_suffix,
        created_at=task.created_at.isoformat(),
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
        elapsed_seconds=task.elapsed_seconds,
        total_images=task.total_images,
        completed_images=task.completed_images,
        failed_images=task.failed_images,
        images=[_to_image_detail(img) for img in paginated_images],
    )


@router.post("/{task_id}/stop")
async def stop_task(task_id: str):
    success, message = await task_manager.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    success, message = await task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.get("/{task_id}/failed-images", response_model=ExportFailedImagesResponse)
async def export_failed_images(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    failed_images = [
        img for img in task.images
        if img.status != ImageBuildStatus.SUCCESS
    ]
    if not failed_images:
        raise HTTPException(status_code=400, detail="该任务没有失败的镜像")

    failed_base_images = [img.base_image for img in failed_images]
    failed_harbor_task_names = [
        img.harbor_task_name for img in failed_images
        if img.harbor_task_name
    ]

    return ExportFailedImagesResponse(
        task_name=f"{task.task_name}-retry",
        agent=task.agent,
        agent_version=task.agent_version,
        dataset=task.dataset,
        base_images=failed_base_images,
        push_dir=task.push_dir,
        build_args=task.build_args,
        retry_count=task.retry_count,
        concurrency=task.concurrency,
        dataset_path=task.dataset_path,
        harbor_task_names=failed_harbor_task_names,
        build_type="script" if task.build_mode == "script" else "opensource",
        dockerfile_content=task.dockerfile_content,
        tag_mode=task.tag_mode,
        tag_suffix=task.tag_suffix,
    )


def _to_summary(task) -> TaskSummary:
    return TaskSummary(
        task_id=task.task_id,
        task_name=task.task_name,
        agent=task.agent,
        agent_version=task.agent_version,
        dataset=task.dataset,
        status=task.status.value,
        build_mode=task.build_mode,
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
        template_name=img.template_name,
        harbor_task_name=img.harbor_task_name,
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
