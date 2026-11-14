"""Unit tests for ZIP packaging service."""

import zipfile
from pathlib import Path
from app.services.zip_service import create_zip_archive


def test_create_zip_archive_multiple_files(tmp_path):
    # Setup test files
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()

    file1 = input_dir / "photo1.jpg"
    file1.write_bytes(b"image data 1")

    file2 = input_dir / "photo2.jpg"
    file2.write_bytes(b"image data 2")

    file3 = input_dir / "video.mp4"
    file3.write_bytes(b"video stream bytes")

    output_zip = tmp_path / "bundle.zip"
    res = create_zip_archive([file1, file2, file3], output_zip)

    assert res == output_zip
    assert output_zip.exists()

    # Original files should remain intact
    assert file1.exists()
    assert file2.exists()
    assert file3.exists()

    # Verify contents of zip
    with zipfile.ZipFile(output_zip, "r") as zf:
        namelist = zf.namelist()
        assert "photo1.jpg" in namelist
        assert "photo2.jpg" in namelist
        assert "video.mp4" in namelist
        assert zf.read("photo1.jpg") == b"image data 1"
        assert zf.read("video.mp4") == b"video stream bytes"


def test_create_zip_archive_duplicate_names(tmp_path):
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()

    file1 = dir1 / "image.jpg"
    file1.write_bytes(b"first image")

    file2 = dir2 / "image.jpg"
    file2.write_bytes(b"second image")

    output_zip = tmp_path / "unique.zip"
    create_zip_archive([file1, file2], output_zip)

    with zipfile.ZipFile(output_zip, "r") as zf:
        namelist = zf.namelist()
        assert len(namelist) == 2
        assert "image.jpg" in namelist
        assert "image_1.jpg" in namelist


def test_create_zip_archive_cascading_collisions(tmp_path):
    dir1 = tmp_path / "d1"
    dir2 = tmp_path / "d2"
    dir3 = tmp_path / "d3"
    dir4 = tmp_path / "d4"
    for d in (dir1, dir2, dir3, dir4):
        d.mkdir()

    f1 = dir1 / "photo.jpg"
    f2 = dir2 / "photo.jpg"
    f3 = dir3 / "photo_1.jpg"
    f4 = dir4 / "photo.jpg"

    f1.write_bytes(b"content 1")
    f2.write_bytes(b"content 2")
    f3.write_bytes(b"content 3")
    f4.write_bytes(b"content 4")

    out_zip = tmp_path / "cascading.zip"
    create_zip_archive([f1, f2, f3, f4], out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert len(namelist) == 4
        # Every entry must be distinct!
        assert len(set(namelist)) == 4
        assert "photo.jpg" in namelist
        assert "photo_1.jpg" in namelist
