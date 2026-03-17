from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import (
    AgentInfo,
    AgentListResponse,
    DatasetImageItem,
    DatasetImageListResponse,
    DatasetListResponse,
    DatasetSummary,
)
from backend.config import AGENTS
from backend.core.database import get_dataset_by_id, list_dataset_images, list_datasets
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
