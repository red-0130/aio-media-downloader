"""Service for bundling downloaded files into ZIP archives."""

import zipfile
from pathlib import Path


def create_zip_archive(files: list[Path], output_zip: Path) -> Path:
    """Bundle a list of file paths into a ZIP archive, keeping individual files intact.

    Returns the path to the created ZIP file.
    """
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    used_arcnames: set[str] = set()

    with zipfile.ZipFile(output_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            if not file_path.exists() or not file_path.is_file():
                continue

            base_name = file_path.name
            stem = file_path.stem
            suffix = file_path.suffix

            # Ensure unique arcname in zip even with cascading name collisions (e.g. photo.jpg, photo.jpg, photo_1.jpg)
            candidate = base_name
            counter = 1
            while candidate in used_arcnames:
                candidate = f"{stem}_{counter}{suffix}"
                counter += 1

            used_arcnames.add(candidate)
            zf.write(file_path, arcname=candidate)

    return output_zip
