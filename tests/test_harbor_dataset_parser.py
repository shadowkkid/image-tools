import os
import textwrap

import pytest

from backend.builder.harbor_dataset_parser import (
    HarborTaskInfo,
    _extract_from_line,
    compute_template_name,
    parse_harbor_dataset,
)


class TestParseHarborDataset:
    def _make_task_dir(self, tmp_path, name, toml_content, dockerfile_content=None):
        """Helper to create a task subdirectory with task.toml and optional Dockerfile."""
        task_dir = tmp_path / name
        task_dir.mkdir()
        (task_dir / "task.toml").write_text(toml_content)
        if dockerfile_content is not None:
            env_dir = task_dir / "environment"
            env_dir.mkdir()
            (env_dir / "Dockerfile").write_text(dockerfile_content)
        return task_dir

    def test_parse_with_docker_image(self, tmp_path):
        self._make_task_dir(
            tmp_path,
            "task-a",
            textwrap.dedent("""\
                [environment]
                docker_image = "python:3.11-slim"
            """),
        )
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].task_name == "task-a"
        assert tasks[0].docker_image == "python:3.11-slim"
        assert tasks[0].base_image == "python:3.11-slim"
        assert tasks[0].dockerfile_path == ""

    def test_parse_with_dockerfile(self, tmp_path):
        self._make_task_dir(
            tmp_path,
            "task-b",
            "[environment]\n",
            "FROM ubuntu:22.04\nRUN apt-get update\n",
        )
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].task_name == "task-b"
        assert tasks[0].docker_image == ""
        assert tasks[0].base_image == "ubuntu:22.04"
        assert tasks[0].dockerfile_path != ""

    def test_parse_multiple_tasks_sorted(self, tmp_path):
        self._make_task_dir(tmp_path, "zoo-task", '[environment]\ndocker_image = "alpine:3"\n')
        self._make_task_dir(tmp_path, "alpha-task", '[environment]\ndocker_image = "debian:12"\n')
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 2
        assert tasks[0].task_name == "alpha-task"
        assert tasks[1].task_name == "zoo-task"

    def test_skips_no_task_toml(self, tmp_path):
        (tmp_path / "some-dir").mkdir()
        self._make_task_dir(tmp_path, "valid", '[environment]\ndocker_image = "python:3"\n')
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].task_name == "valid"

    def test_skips_template_placeholder(self, tmp_path):
        self._make_task_dir(
            tmp_path,
            "templated",
            '[environment]\ndocker_image = "{docker_image}"\n',
        )
        self._make_task_dir(tmp_path, "real", '[environment]\ndocker_image = "python:3"\n')
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].task_name == "real"

    def test_skips_no_dockerfile_no_docker_image(self, tmp_path):
        self._make_task_dir(tmp_path, "empty", "[environment]\n")
        self._make_task_dir(tmp_path, "ok", '[environment]\ndocker_image = "alpine"\n')
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].task_name == "ok"

    def test_raises_invalid_path(self):
        with pytest.raises(ValueError, match="does not exist"):
            parse_harbor_dataset("/nonexistent/path")

    def test_raises_no_tasks_found(self, tmp_path):
        with pytest.raises(ValueError, match="No valid harbor tasks"):
            parse_harbor_dataset(str(tmp_path))

    def test_multi_stage_dockerfile_uses_last_from(self, tmp_path):
        self._make_task_dir(
            tmp_path,
            "multistage",
            "[environment]\n",
            "FROM golang:1.21 AS builder\nRUN go build\nFROM alpine:3.18\nCOPY --from=builder /app /app\n",
        )
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].base_image == "alpine:3.18"

    def test_docker_image_takes_priority_over_dockerfile(self, tmp_path):
        self._make_task_dir(
            tmp_path,
            "both",
            '[environment]\ndocker_image = "prebuilt:v1"\n',
            "FROM ignored:latest\n",
        )
        tasks = parse_harbor_dataset(str(tmp_path))
        assert len(tasks) == 1
        assert tasks[0].base_image == "prebuilt:v1"
        assert tasks[0].dockerfile_path == ""


class TestComputeTemplateName:
    def test_basic(self, tmp_path):
        env_dir = tmp_path / "my-task" / "environment"
        env_dir.mkdir(parents=True)
        (env_dir / "Dockerfile").write_text("FROM ubuntu:22.04\n")
        result = compute_template_name("my-dataset", "my-task", str(tmp_path / "my-task"))
        assert result.startswith("my-dataset__my-task__")
        assert len(result.split("__")[-1]) == 8

    def test_deterministic(self, tmp_path):
        env_dir = tmp_path / "task" / "environment"
        env_dir.mkdir(parents=True)
        (env_dir / "Dockerfile").write_text("FROM python:3.11\n")
        r1 = compute_template_name("ds", "task", str(tmp_path / "task"))
        r2 = compute_template_name("ds", "task", str(tmp_path / "task"))
        assert r1 == r2

    def test_different_envs_different_names(self, tmp_path):
        for name, content in [("t1", "FROM python:3.11\n"), ("t2", "FROM python:3.12\n")]:
            env_dir = tmp_path / name / "environment"
            env_dir.mkdir(parents=True)
            (env_dir / "Dockerfile").write_text(content)
        r1 = compute_template_name("ds", "t1", str(tmp_path / "t1"))
        r2 = compute_template_name("ds", "t2", str(tmp_path / "t2"))
        assert r1 != r2

    def test_replaces_dot(self, tmp_path):
        env_dir = tmp_path / "sub.task" / "environment"
        env_dir.mkdir(parents=True)
        (env_dir / "Dockerfile").write_text("FROM image:latest\n")
        result = compute_template_name("org", "sub.task", str(tmp_path / "sub.task"))
        assert "." not in result


class TestExtractFromLine:
    def test_simple(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text("FROM ubuntu:22.04\n")
        assert _extract_from_line(df) == "ubuntu:22.04"

    def test_case_insensitive(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text("from python:3.11\n")
        assert _extract_from_line(df) == "python:3.11"

    def test_empty(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text("RUN echo hello\n")
        assert _extract_from_line(df) == ""

    def test_platform_flag(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text("FROM --platform=linux/amd64 ubuntu:22.04\n")
        assert _extract_from_line(df) == "ubuntu:22.04"

    def test_platform_with_as(self, tmp_path):
        df = tmp_path / "Dockerfile"
        df.write_text("FROM --platform=linux/amd64 golang:1.21 AS builder\n")
        assert _extract_from_line(df) == "golang:1.21"
