import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "portable_build", Path(__file__).parents[1] / "packaging/build.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_payload_size_counts_symlink_metadata_without_duplicating_library(tmp_path):
    (tmp_path / "library.bin").write_bytes(b"x" * 1024)
    try:
        (tmp_path / "alias.bin").symlink_to("library.bin")
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert build.payload_size(tmp_path) == 1024 + len("library.bin")


def test_payload_size_rejects_external_symlink(tmp_path):
    outside = tmp_path.parent / "outside-library.bin"
    outside.write_bytes(b"x")
    try:
        (tmp_path / "alias.bin").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError):
        build.payload_size(tmp_path)


def test_archive_preserves_library_alias_instead_of_expanding_copy(tmp_path):
    import zipfile, stat

    package = tmp_path / "App"
    package.mkdir()
    (package / "library").write_bytes(b"x" * 1024)
    try:
        (package / "alias").symlink_to("library")
    except OSError:
        pytest.skip("Symlinks unavailable")
    destination = tmp_path / "portable.zip"
    build.archive_package(package, destination)
    with zipfile.ZipFile(destination) as z:
        link = z.getinfo("App/alias")
        assert stat.S_ISLNK(link.external_attr >> 16)
        assert z.read(link) == "library".encode()
        assert z.read("App/library") == b"x" * 1024
