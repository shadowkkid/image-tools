from fastapi import APIRouter

from backend.api.schemas import (
    CheckAuthRequest,
    CheckAuthResponse,
    LoginRequest,
    LoginResponse,
)
from backend.core.docker_service import DockerService, _parse_registry_host

router = APIRouter(prefix="/api/registry", tags=["registry"])
docker_service = DockerService()


@router.post("/check-auth", response_model=CheckAuthResponse)
async def check_auth(req: CheckAuthRequest):
    registry_host = _parse_registry_host(req.registry)
    authenticated, message = docker_service.check_registry_auth(req.registry)
    return CheckAuthResponse(
        authenticated=authenticated,
        registry=registry_host,
        message=message,
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    success, message = await docker_service.login(
        registry=req.registry,
        username=req.username,
        password=req.password,
    )
    return LoginResponse(success=success, message=message)
