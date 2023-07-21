import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

import freezegun
import pytest
from _pytest.assertion.util import _diff_text

from tests.utils.compare_rdf import compare_rdf
from tests.utils.dirutils import are_dir_trees_equal


class Snapshot(ABC):
    def __init__(self, path: Path, config: pytest.Config) -> None:
        self.path = path
        self.config = config
        self.eq_state = ""

    def __eq__(self, other: object) -> bool:
        __tracebackhide__ = True
        if self.config.getoption("generate_snapshots"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return self.generate_snapshot(other)
        else:
            if not self.path.exists():
                raise FileNotFoundError(
                    f"snapshot {self.path} does not exist. To generate snapshot run test with --generate-snapshots"
                )
            return self.compare_to_snapshot(other)

    @abstractmethod
    def generate_snapshot(self, updated: object) -> bool:
        pass

    @abstractmethod
    def compare_to_snapshot(self, other: object) -> bool:
        pass


class SnapshotFile(Snapshot):
    def __init__(self, path: Path, config: pytest.Config) -> None:
        super().__init__(path, config)

    def generate_snapshot(self, source: object) -> bool:
        # if we got a path, copy it into the snapshot directory
        if isinstance(source, Path):
            shutil.copy2(source, self.path)
            return True
        # if we got a string, use that as the content for the snapshot file
        if isinstance(source, str):
            with open(self.path, "w") as dest_file:
                dest_file.write(source)
            return True
        # we got something we don't know how to handle
        __tracebackhide__ = True
        raise TypeError(f"cannot generate snapshot from {source}")

    def compare_to_snapshot(self, other: object) -> bool:
        with open(self.path, "r") as snapshot_file:
            expected = snapshot_file.read()

        if isinstance(other, Path):
            with open(other, "r") as compare_file:
                actual = compare_file.read()
        elif isinstance(other, str):
            actual = other
        else:
            __tracebackhide__ = True
            raise TypeError(f"cannot compare snapshot to {other}")

        if self.path.suffix == ".ttl":
            self.eq_state = compare_rdf(actual, expected)
            return self.eq_state is None
        else:
            is_eq = actual == expected
            if not is_eq:
                self.eq_state = _diff_text(actual, expected, self.config.getoption("verbose"))
            return is_eq


class SnapshotDirectory(Snapshot):
    def __init__(self, path: Path, config: pytest.Config) -> None:
        super().__init__(path, config)

    def generate_snapshot(self, source: object) -> bool:
        # if we got a path, recursively copy the whole directory into the snapshot directory
        if isinstance(source, Path):
            shutil.rmtree(self.path, ignore_errors=True)
            shutil.copytree(source, self.path)
            return True
        # we got something we don't know how to handle
        __tracebackhide__ = True
        raise TypeError(f"cannot generate snapshot from {source}")

    def compare_to_snapshot(self, other: object) -> bool:
        if isinstance(other, Path):
            self.eq_state = are_dir_trees_equal(self.path, other)
            return self.eq_state is None
        else:
            __tracebackhide__ = True
            raise TypeError(f"cannot compare snapshot to {other}")


@pytest.fixture
def snapshot_path(request) -> Callable[[str], Path]:
    def get_path(relative_path):
        return request.path.parent / "__snapshots__" / relative_path

    return get_path


@pytest.fixture
def snapshot(snapshot_path, pytestconfig) -> Callable[[str], Snapshot]:
    def get_snapshot(relative_path):
        path = snapshot_path(relative_path)
        if not path.suffix:
            return SnapshotDirectory(path, pytestconfig)
        else:
            return SnapshotFile(path, pytestconfig)

    return get_snapshot


@pytest.fixture
def input_path(request) -> Callable[[str], Path]:
    def get_path(filename):
        return str(request.path.parent / "input" / filename)

    return get_path


@pytest.fixture(autouse=True)
def frozen_time():
    with freezegun.freeze_time("2000-01-01") as ft:
        yield ft


def pytest_addoption(parser):
    parser.addoption(
        "--generate-snapshots",
        action="store_true",
        help="Generate new files into __snapshot__ directories instead of checking against existing files",
    )


def pytest_assertrepr_compare(config, op, left, right):
    if op == "==" and isinstance(right, Snapshot):
        return [f"value matches snapshot {right.path}"] + right.eq_state.split("\n")
