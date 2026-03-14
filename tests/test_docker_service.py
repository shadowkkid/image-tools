import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.docker_service import DockerService, _parse_registry_host


class TestParseRegistryHost:
    def test_with_prefix(self):
        assert _parse_registry_host("registry.sensecore.tech/ccr-sandbox-swe") == "registry.sensecore.tech"

    def test_plain_host(self):
        assert _parse_registry_host("registry.sensecore.tech") == "registry.sensecore.tech"

    def test_host_with_port(self):
        assert _parse_registry_host("localhost:5000/myrepo") == "localhost:5000"

    def test_dockerhub(self):
        assert _parse_registry_host("docker.io/library") == "docker.io"


class TestCheckRegistryAuth:
    def test_authenticated(self, tmp_path):
        config = {"auths": {"registry.sensecore.tech": {"auth": "dXNlcjpwYXNz"}}}
        config_file = tmp_path / ".docker" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config))

        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            with patch("backend.core.docker_service.os.path.expanduser",
                       return_value=str(config_file)):
                ok, msg = DockerService.check_registry_auth("registry.sensecore.tech/ccr-sandbox")
                assert ok is True

    def test_not_authenticated(self, tmp_path):
        config = {"auths": {"other.registry.io": {"auth": "abc"}}}
        config_file = tmp_path / ".docker" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(config))

        with patch("backend.core.docker_service.os.path.expanduser",
                   return_value=str(config_file)):
            ok, msg = DockerService.check_registry_auth("registry.sensecore.tech/ccr-sandbox")
            assert ok is False

    def test_no_config_file(self):
        with patch("backend.core.docker_service.os.path.expanduser",
                   return_value="/nonexistent/config.json"):
            ok, msg = DockerService.check_registry_auth("registry.sensecore.tech")
            assert ok is False


class TestDockerLogin:
    @pytest.mark.asyncio
    async def test_login_success(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Login Succeeded\n", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.login("registry.sensecore.tech", "user", "pass")
            assert ok is True
            assert "Login Succeeded" in msg

    @pytest.mark.asyncio
    async def test_login_failure(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"unauthorized"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.login("registry.sensecore.tech", "user", "wrong")
            assert ok is False


class TestDockerTag:
    @pytest.mark.asyncio
    async def test_tag_success(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.tag("src:v1", "dst:v1")
            assert ok is True


class TestDockerRemoveImage:
    @pytest.mark.asyncio
    async def test_remove_success(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Untagged: img:v1\n", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.remove_image("img:v1")
            assert ok is True

    @pytest.mark.asyncio
    async def test_remove_failure(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"No such image"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.remove_image("nonexistent:v1")
            assert ok is False


class TestDockerPruneImages:
    @pytest.mark.asyncio
    async def test_prune_success(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"Total reclaimed space: 100MB\n", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.prune_images()
            assert ok is True

    @pytest.mark.asyncio
    async def test_prune_failure(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await DockerService.prune_images()
            assert ok is False
