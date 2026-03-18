from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.core.task_models import (
    BuildTask,
    ImageBuildInfo,
    ImageBuildStatus,
    TaskStatus,
)
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_task(images_status: list[ImageBuildStatus]) -> BuildTask:
    """Create a BuildTask with images at given statuses."""
    task = BuildTask(
        task_name="test-task",
        deps_image="deps:latest",
        push_dir="registry.example.com/repo",
        base_images=[f"img-{i}:latest" for i in range(len(images_status))],
        agent="OpenHands",
        agent_version="0.54.0",
        dataset="swe-bench",
        build_args=["--network=host"],
        retry_count=1,
        concurrency=4,
        status=TaskStatus.COMPLETED,
    )
    task.images = [
        ImageBuildInfo(
            base_image=f"img-{i}:latest",
            target_image=f"registry.example.com/repo/img-{i}:latest",
            status=status,
        )
        for i, status in enumerate(images_status)
    ]
    return task


class TestExportFailedImages:
    def test_export_failed_images_success(self, client):
        task = _make_task([
            ImageBuildStatus.SUCCESS,
            ImageBuildStatus.FAILED,
            ImageBuildStatus.CANCELLED,
            ImageBuildStatus.PENDING,
        ])

        with patch("backend.api.tasks.task_manager") as mock_tm:
            mock_tm.get_task.return_value = task
            resp = client.get(f"/api/tasks/{task.task_id}/failed-images")

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_name"] == "test-task-retry"
        assert data["agent"] == "OpenHands"
        assert data["agent_version"] == "0.54.0"
        assert data["dataset"] == "swe-bench"
        assert data["push_dir"] == "registry.example.com/repo"
        assert data["build_args"] == ["--network=host"]
        assert data["retry_count"] == 1
        assert data["concurrency"] == 4
        # Only non-SUCCESS images
        assert set(data["base_images"]) == {"img-1:latest", "img-2:latest", "img-3:latest"}

    def test_export_failed_images_no_failures(self, client):
        task = _make_task([ImageBuildStatus.SUCCESS, ImageBuildStatus.SUCCESS])

        with patch("backend.api.tasks.task_manager") as mock_tm:
            mock_tm.get_task.return_value = task
            resp = client.get(f"/api/tasks/{task.task_id}/failed-images")

        assert resp.status_code == 400
        assert "没有失败的镜像" in resp.json()["detail"]

    def test_export_failed_images_task_not_found(self, client):
        with patch("backend.api.tasks.task_manager") as mock_tm:
            mock_tm.get_task.return_value = None
            resp = client.get("/api/tasks/nonexistent/failed-images")

        assert resp.status_code == 404

    def test_export_failed_images_building_status_included(self, client):
        """Images still in BUILDING status should be included as failed."""
        task = _make_task([ImageBuildStatus.SUCCESS, ImageBuildStatus.BUILDING])

        with patch("backend.api.tasks.task_manager") as mock_tm:
            mock_tm.get_task.return_value = task
            resp = client.get(f"/api/tasks/{task.task_id}/failed-images")

        assert resp.status_code == 200
        assert resp.json()["base_images"] == ["img-1:latest"]
