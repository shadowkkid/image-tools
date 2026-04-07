from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    AgentInfo,
    AgentListResponse,
    BatchDeleteRequest,
    DatasetImageItem,
    DatasetImageListResponse,
    DatasetListResponse,
    DatasetSummary,
    HarborTaskPreview,
    ParseDatasetRequest,
    ParseDatasetResponse,
)
from backend.config import AGENTS
from backend.core.database import (
    delete_dataset,
    delete_dataset_images,
    get_dataset_by_id,
    list_dataset_images,
    list_datasets,
)
from backend.core.task_manager import task_manager

router = APIRouter(prefix="/api", tags=["datasets"])


@router.get("/agents", response_model=AgentListResponse)
async def get_agents():
    agents = []
    for name, cfg in AGENTS.items():
        agents.append(AgentInfo(
            name=name,
            has_versions=cfg["has_versions"],
            versions=list(cfg.get("versions", {}).keys()) if cfg["has_versions"] else [],
        ))
    return AgentListResponse(agents=agents)


@router.get("/datasets", response_model=DatasetListResponse)
async def get_datasets(
    agent: str = Query("", description="Filter by agent"),
    agent_version: str = Query("", description="Filter by agent version"),
    search: str = Query("", description="Fuzzy search by name"),
):
    rows = list_datasets(
        agent=agent, agent_version=agent_version,
        search=search, db_path=task_manager.db_path,
    )
    return DatasetListResponse(
        datasets=[
            DatasetSummary(
                id=r["id"],
                name=r["name"],
                agent=r["agent"],
                agent_version=r["agent_version"],
                image_count=r["image_count"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
    )


@router.get("/datasets/{dataset_id}/images", response_model=DatasetImageListResponse)
async def get_dataset_images(
    dataset_id: int,
    search: str = Query("", description="Fuzzy search by image name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    ds = get_dataset_by_id(dataset_id, db_path=task_manager.db_path)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    rows, total = list_dataset_images(
        dataset_id, search=search, page=page, page_size=page_size, db_path=task_manager.db_path
    )
    return DatasetImageListResponse(
        images=[
            DatasetImageItem(
                id=r["id"],
                image_name=r["image_name"],
                task_id=r["task_id"],
                task_name=r["task_name"],
                created_at=r["created_at"],
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/datasets/{dataset_id}")
async def remove_dataset(dataset_id: int):
    deleted = delete_dataset(dataset_id, db_path=task_manager.db_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"success": True, "message": "数据集已删除"}


@router.post("/datasets/{dataset_id}/images/batch-delete")
async def batch_delete_images(dataset_id: int, req: BatchDeleteRequest):
    ds = get_dataset_by_id(dataset_id, db_path=task_manager.db_path)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    count = delete_dataset_images(req.ids, db_path=task_manager.db_path)
    return {"success": True, "deleted": count}


@router.post("/harbor/parse-dataset", response_model=ParseDatasetResponse)
async def parse_harbor_dataset_endpoint(req: ParseDatasetRequest):
    """Parse a harbor dataset and return task previews.

    Accepts either a dataset@version ref or a local path.
    """
    from backend.builder.harbor_dataset_parser import resolve_and_parse

    try:
        local_path, tasks = resolve_and_parse(req.dataset_ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ParseDatasetResponse(
        tasks=[
            HarborTaskPreview(
                task_name=t.task_name,
                base_image=t.base_image,
                has_dockerfile=bool(t.dockerfile_path),
                has_docker_image=bool(t.docker_image),
            )
            for t in tasks
        ],
        total=len(tasks),
        dataset_path=local_path,
    )
