"""Service for bundling downloaded files into ZIP archives."""

import zipfile
from pathlib import Path

from app.services import naming_service


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

            arcname = naming_service.disambiguate_filename(file_path.name, used_arcnames)
            zf.write(file_path, arcname=arcname)

    return output_zip
