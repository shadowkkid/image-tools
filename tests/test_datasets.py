import pytest

from backend.core.database import (
    add_dataset_image,
    ensure_dataset,
    get_dataset_by_id,
    init_db,
    list_dataset_images,
    list_datasets,
    save_task,
)
from backend.core.task_models import BuildTask, ImageBuildInfo


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database."""
    path = str(tmp_path / "test_datasets.db")
    init_db(path)
    return path


class TestEnsureDataset:
    def test_create_new_dataset(self, db_path):
        ds_id = ensure_dataset("my-dataset", db_path)
        assert ds_id > 0

    def test_idempotent(self, db_path):
        id1 = ensure_dataset("ds-1", db_path)
        id2 = ensure_dataset("ds-1", db_path)
        assert id1 == id2

    def test_different_names_different_ids(self, db_path):
        id1 = ensure_dataset("ds-a", db_path)
        id2 = ensure_dataset("ds-b", db_path)
        assert id1 != id2


class TestAddDatasetImage:
    def test_add_image(self, db_path):
        # Create a task first (needed for FK constraint)
        task = BuildTask(
            task_name="t",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04"],
            dataset="ds-1",
        )
        task.images.append(
            ImageBuildInfo(base_image="ubuntu:22.04", target_image="reg/repo/ubuntu:22.04")
        )
        save_task(task, db_path)

        add_dataset_image("ds-1", "reg/repo/ubuntu:22.04", task.task_id, db_path)

        rows, total = list_dataset_images(
            ensure_dataset("ds-1", db_path), db_path=db_path
        )
        assert total == 1
        assert rows[0]["image_name"] == "reg/repo/ubuntu:22.04"
        assert rows[0]["task_name"] == "t"

    def test_add_multiple_images(self, db_path):
        task = BuildTask(
            task_name="multi",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1", "b:2"],
            dataset="ds-2",
        )
        task.images = [
            ImageBuildInfo(base_image="a:1", target_image="reg/repo/a:1"),
            ImageBuildInfo(base_image="b:2", target_image="reg/repo/b:2"),
        ]
        save_task(task, db_path)

        add_dataset_image("ds-2", "reg/repo/a:1", task.task_id, db_path)
        add_dataset_image("ds-2", "reg/repo/b:2", task.task_id, db_path)

        ds_id = ensure_dataset("ds-2", db_path)
        rows, total = list_dataset_images(ds_id, db_path=db_path)
        assert total == 2


class TestListDatasets:
    def test_empty(self, db_path):
        result = list_datasets(db_path=db_path)
        assert result == []

    def test_list_with_counts(self, db_path):
        task = BuildTask(
            task_name="t",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1"],
            dataset="ds-count",
        )
        task.images.append(
            ImageBuildInfo(base_image="a:1", target_image="reg/repo/a:1")
        )
        save_task(task, db_path)

        ensure_dataset("ds-count", db_path)
        add_dataset_image("ds-count", "reg/repo/a:1", task.task_id, db_path)

        result = list_datasets(db_path=db_path)
        assert len(result) == 1
        assert result[0]["name"] == "ds-count"
        assert result[0]["image_count"] == 1

    def test_search_filter(self, db_path):
        ensure_dataset("alpha-dataset", db_path)
        ensure_dataset("beta-dataset", db_path)
        ensure_dataset("gamma-other", db_path)

        result = list_datasets(search="dataset", db_path=db_path)
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"alpha-dataset", "beta-dataset"}

    def test_empty_search_returns_all(self, db_path):
        ensure_dataset("ds-x", db_path)
        ensure_dataset("ds-y", db_path)

        result = list_datasets(search="", db_path=db_path)
        assert len(result) == 2


class TestListDatasetImages:
    def _setup_dataset_with_images(self, db_path, count=5):
        task = BuildTask(
            task_name="paging-task",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=[f"img:{i}" for i in range(count)],
            dataset="paging-ds",
        )
        task.images = [
            ImageBuildInfo(base_image=f"img:{i}", target_image=f"reg/repo/img:{i}")
            for i in range(count)
        ]
        save_task(task, db_path)

        for i in range(count):
            add_dataset_image("paging-ds", f"reg/repo/img:{i}", task.task_id, db_path)

        return ensure_dataset("paging-ds", db_path)

    def test_pagination(self, db_path):
        ds_id = self._setup_dataset_with_images(db_path, count=5)

        rows, total = list_dataset_images(ds_id, page=1, page_size=2, db_path=db_path)
        assert total == 5
        assert len(rows) == 2

        rows2, total2 = list_dataset_images(ds_id, page=2, page_size=2, db_path=db_path)
        assert total2 == 5
        assert len(rows2) == 2

        rows3, total3 = list_dataset_images(ds_id, page=3, page_size=2, db_path=db_path)
        assert total3 == 5
        assert len(rows3) == 1

    def test_search_by_image_name(self, db_path):
        task = BuildTask(
            task_name="search-task",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["ubuntu:22.04", "alpine:3"],
            dataset="search-ds",
        )
        task.images = [
            ImageBuildInfo(base_image="ubuntu:22.04", target_image="reg/repo/ubuntu:22.04"),
            ImageBuildInfo(base_image="alpine:3", target_image="reg/repo/alpine:3"),
        ]
        save_task(task, db_path)

        add_dataset_image("search-ds", "reg/repo/ubuntu:22.04", task.task_id, db_path)
        add_dataset_image("search-ds", "reg/repo/alpine:3", task.task_id, db_path)

        ds_id = ensure_dataset("search-ds", db_path)
        rows, total = list_dataset_images(ds_id, search="ubuntu", db_path=db_path)
        assert total == 1
        assert rows[0]["image_name"] == "reg/repo/ubuntu:22.04"


class TestGetDatasetById:
    def test_existing(self, db_path):
        ds_id = ensure_dataset("existing-ds", db_path)
        result = get_dataset_by_id(ds_id, db_path)
        assert result is not None
        assert result["name"] == "existing-ds"

    def test_not_found(self, db_path):
        result = get_dataset_by_id(99999, db_path)
        assert result is None


class TestDatasetFieldInTask:
    def test_task_with_dataset(self, db_path):
        from backend.core.database import load_all_tasks

        task = BuildTask(
            task_name="ds-task",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1"],
            dataset="my-dataset",
        )
        task.images.append(
            ImageBuildInfo(base_image="a:1", target_image="reg/repo/a:1")
        )
        save_task(task, db_path)

        loaded = load_all_tasks(db_path)
        t = loaded[task.task_id]
        assert t.dataset == "my-dataset"

    def test_task_without_dataset(self, db_path):
        from backend.core.database import load_all_tasks

        task = BuildTask(
            task_name="no-ds-task",
            deps_image="deps:v1",
            push_dir="reg/repo",
            base_images=["a:1"],
        )
        task.images.append(
            ImageBuildInfo(base_image="a:1", target_image="reg/repo/a:1")
        )
        save_task(task, db_path)

        loaded = load_all_tasks(db_path)
        t = loaded[task.task_id]
        assert t.dataset == ""
