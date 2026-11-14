"""Tier 2 Boundary Tests: B06 - Auto-ZIP Bundling & Archive Integrity Boundaries.

Covers:
- Filename collision handling inside ZIP archives
- Cascading collision resolution (e.g. existing stem_1 collisions)
- Empty file list handling (valid empty archive creation)
- Zero-byte (empty) file inclusion
- Multi-language Unicode and Emoji filenames inside ZIP
- Zip integrity CRC32 verification (zf.testzip())
- DEFLATED compression ratio on compressible vs binary data
- Graceful skipping of non-existent paths and directory objects
- Large bundle scalability (50+ bundled media items)
- Parent directory auto-creation for destination archives
- ZIP file cleanup when task directories expire
- Verification of uncorrupted archive extraction
"""

import io
import zipfile
from pathlib import Path
import pytest

from app.services import cleaner, zip_service


def test_zip_identical_filename_collisions_resolved(tmp_path: Path):
    """Verify identical basenames from different folders are disambiguated with _1, _2 suffixes."""
    dir1 = tmp_path / "part1"
    dir2 = tmp_path / "part2"
    dir3 = tmp_path / "part3"
    dir1.mkdir()
    dir2.mkdir()
    dir3.mkdir()

    f1 = dir1 / "photo.jpg"
    f2 = dir2 / "photo.jpg"
    f3 = dir3 / "photo.jpg"
    f1.write_bytes(b"content 1")
    f2.write_bytes(b"content 2")
    f3.write_bytes(b"content 3")

    out_zip = tmp_path / "bundle.zip"
    zip_service.create_zip_archive([f1, f2, f3], out_zip)

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert len(namelist) == 3
        assert namelist == ["photo.jpg", "photo_1.jpg", "photo_2.jpg"]
        assert zf.read("photo.jpg") == b"content 1"
        assert zf.read("photo_1.jpg") == b"content 2"
        assert zf.read("photo_2.jpg") == b"content 3"


def test_zip_cascading_collisions_resolution(tmp_path: Path):
    """Verify collision resolution correctly handles pre-existing numbered filenames."""
    dir1 = tmp_path / "c1"
    dir2 = tmp_path / "c2"
    dir3 = tmp_path / "c3"
    dir1.mkdir()
    dir2.mkdir()
    dir3.mkdir()

    # Pre-existing name collision condition: photo.jpg, photo_1.jpg, photo.jpg
    f1 = dir1 / "photo.jpg"
    f2 = dir2 / "photo_1.jpg"
    f3 = dir3 / "photo.jpg"
    f1.write_bytes(b"first")
    f2.write_bytes(b"existing _1")
    f3.write_bytes(b"second duplicate")

    out_zip = tmp_path / "cascade.zip"
    zip_service.create_zip_archive([f1, f2, f3], out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert len(namelist) == 3
        # Should resolve to photo.jpg, photo_1.jpg, photo_2.jpg
        assert "photo.jpg" in namelist
        assert "photo_1.jpg" in namelist
        assert "photo_2.jpg" in namelist


def test_zip_empty_file_list_creates_valid_empty_zip(tmp_path: Path):
    """Verify passing an empty list creates a valid 22-byte empty ZIP with no files."""
    out_zip = tmp_path / "empty.zip"
    zip_service.create_zip_archive([], out_zip)

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip, "r") as zf:
        assert len(zf.namelist()) == 0
        assert zf.testzip() is None


def test_zip_zero_byte_files_handled_cleanly(tmp_path: Path):
    """Verify 0-byte (empty) media files are bundled without corruption or error."""
    empty1 = tmp_path / "empty1.jpg"
    empty2 = tmp_path / "empty2.mp4"
    empty1.touch()
    empty2.touch()

    out_zip = tmp_path / "empty_files.zip"
    zip_service.create_zip_archive([empty1, empty2], out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        assert zf.testzip() is None
        assert zf.read("empty1.jpg") == b""
        assert zf.read("empty2.mp4") == b""


def test_zip_unicode_and_emoji_filenames(tmp_path: Path):
    """Verify Japanese, Arabic, Cyrillic, and Emoji filenames inside archive preserve UTF-8 encoding."""
    f_jp = tmp_path / "テスト_動画.mp4"
    f_ar = tmp_path / "فيديو_رائع.mp4"
    f_ru = tmp_path / "видео_клип.mp4"
    f_em = tmp_path / "🔥_highlight_🚀.jpg"

    f_jp.write_text("jp", encoding="utf-8")
    f_ar.write_text("ar", encoding="utf-8")
    f_ru.write_text("ru", encoding="utf-8")
    f_em.write_text("em", encoding="utf-8")

    out_zip = tmp_path / "unicode_bundle.zip"
    zip_service.create_zip_archive([f_jp, f_ar, f_ru, f_em], out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        assert "テスト_動画.mp4" in names
        assert "فيديو_رائع.mp4" in names
        assert "видео_клип.mp4" in names
        assert "🔥_highlight_🚀.jpg" in names


def test_zip_integrity_crc_checks(tmp_path: Path):
    """Verify zip archive CRC32 checksums match for all contained entries."""
    payloads = {
        "file1.bin": b"\x00\xFF\xAA\x55" * 1024,
        "file2.bin": b"Random text payload for CRC verification" * 50,
        "file3.bin": bytes(range(256)),
    }
    file_paths = []
    for name, data in payloads.items():
        fp = tmp_path / name
        fp.write_bytes(data)
        file_paths.append(fp)

    out_zip = tmp_path / "crc_check.zip"
    zip_service.create_zip_archive(file_paths, out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        # testzip() returns None if all file CRCs match
        corrupt_file = zf.testzip()
        assert corrupt_file is None

        for name, data in payloads.items():
            assert zf.read(name) == data


def test_zip_deflated_compression_ratio(tmp_path: Path):
    """Verify ZIP_DEFLATED compression reduces the size of compressible text files."""
    compressible_data = b"REPEATING TEXT SEQUENCE 1234567890\n" * 5000
    comp_file = tmp_path / "large_text.txt"
    comp_file.write_bytes(compressible_data)
    uncompressed_size = len(compressible_data)

    out_zip = tmp_path / "compressed.zip"
    zip_service.create_zip_archive([comp_file], out_zip)

    zip_size = out_zip.stat().st_size
    # Compression ratio should be > 5x (zip_size < uncompressed_size / 5)
    assert zip_size < (uncompressed_size / 5)


def test_zip_skips_non_existent_and_directory_paths(tmp_path: Path):
    """Verify missing file paths and directory objects in input list are safely skipped."""
    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("ok")
    missing_file = tmp_path / "does_not_exist.txt"
    sub_dir = tmp_path / "some_dir"
    sub_dir.mkdir()

    out_zip = tmp_path / "skip_test.zip"
    zip_service.create_zip_archive([valid_file, missing_file, sub_dir], out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert namelist == ["valid.txt"]


def test_zip_large_bundle_file_count(tmp_path: Path):
    """Verify archiving 50 files into a single bundle operates accurately."""
    files = []
    sub = tmp_path / "items"
    sub.mkdir()
    for i in range(50):
        fp = sub / f"item_{i:02d}.jpg"
        fp.write_bytes(f"item_{i}_data".encode("utf-8"))
        files.append(fp)

    out_zip = tmp_path / "large_50_bundle.zip"
    zip_service.create_zip_archive(files, out_zip)

    with zipfile.ZipFile(out_zip, "r") as zf:
        assert len(zf.namelist()) == 50
        assert zf.testzip() is None


def test_zip_output_in_nested_directory_creation(tmp_path: Path):
    """Verify create_zip_archive creates non-existent destination subdirectories automatically."""
    deep_out_zip = tmp_path / "nested" / "sub" / "folder" / "archive.zip"
    dummy = tmp_path / "dummy.txt"
    dummy.write_text("dummy")

    assert not deep_out_zip.parent.exists()
    zip_service.create_zip_archive([dummy], deep_out_zip)
    assert deep_out_zip.exists()


def test_zip_cleanup_with_task_expiration(tmp_path: Path):
    """Verify that when a task directory expires, bundled ZIP archives are removed."""
    task_dir = tmp_path / "task-zip-expire"
    task_dir.mkdir()
    zip_file = task_dir / "bundle.zip"
    zip_service.create_zip_archive([], zip_file)
    assert zip_file.exists()

    # Age directory past TTL
    import os, time

    os.utime(task_dir, (time.time() - 4000, time.time() - 4000))
    deleted = cleaner.cleanup_old_downloads(tmp_path, ttl_minutes=60)
    assert deleted == 1
    assert not task_dir.exists()
    assert not zip_file.exists()


def test_zip_individual_files_remain_intact_after_bundling(tmp_path: Path):
    """Verify source files remain intact and accessible after being packaged into ZIP."""
    f1 = tmp_path / "original_1.mp4"
    f2 = tmp_path / "original_2.mp4"
    f1.write_bytes(b"content 1")
    f2.write_bytes(b"content 2")

    out_zip = tmp_path / "bundle.zip"
    zip_service.create_zip_archive([f1, f2], out_zip)

    # Both individual files still exist with unchanged contents
    assert f1.exists()
    assert f2.exists()
    assert f1.read_bytes() == b"content 1"
    assert f2.read_bytes() == b"content 2"
