"""gallery-dl wrapper service for photo carousels, galleries, and stories."""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from app.services.ytdlp_service import (
    ExtractionError,
    AuthRequiredError,
    RateLimitError,
    classify_error,
)


def parse_gallerydl_json(raw_text: str) -> list[dict[str, Any]]:
    """Parse gallery-dl JSON output (formatted JSON array, lines, or tuples).

    Extracts media item dictionaries (type 3 or direct dicts) and combines
    directory/category metadata (type 2) if present. If extraction was aborted
    with an error (type -1), raises the classified specialized exception.
    """
    if not raw_text or not raw_text.strip():
        return []

    clean_text = raw_text.strip()
    parsed_entries: list[Any] = []

    try:
        data = json.loads(clean_text)
        if isinstance(data, list):
            parsed_entries = data
        elif isinstance(data, dict):
            parsed_entries = [data]
    except json.JSONDecodeError:
        # Fallback to line-by-line or streaming JSON
        for line in clean_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                line_data = json.loads(line)
                if isinstance(line_data, list):
                    parsed_entries.append(line_data)
                elif isinstance(line_data, dict):
                    parsed_entries.append(line_data)
            except json.JSONDecodeError:
                continue

    items: list[dict[str, Any]] = []
    type2_entries: list[dict[str, Any]] = []
    directory_metadata: dict[str, Any] = {}
    error_messages: list[str] = []

    for entry in parsed_entries:
        if isinstance(entry, dict):
            items.append(entry)
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            type_id = entry[0]
            # Type -1: Error / AbortExtraction record
            if type_id == -1:
                if isinstance(entry[1], dict):
                    err_msg = entry[1].get("message") or entry[1].get("error") or str(entry[1])
                    error_messages.append(err_msg)
                elif isinstance(entry[1], str):
                    error_messages.append(entry[1])
            # Type 2: Directory / Category metadata
            elif type_id == 2:
                meta = (
                    entry[2]
                    if len(entry) >= 3 and isinstance(entry[2], dict)
                    else (entry[1] if isinstance(entry[1], dict) else None)
                )
                if meta:
                    directory_metadata.update(meta)
                    type2_entries.append(meta)
            # Type 3: Media item [3, url, metadata_dict]
            elif type_id == 3:
                media_meta: dict[str, Any] = {}
                if len(entry) >= 3 and isinstance(entry[2], dict):
                    media_meta = dict(entry[2])
                elif isinstance(entry[1], dict):
                    media_meta = dict(entry[1])

                if isinstance(entry[1], str) and not media_meta.get("url"):
                    media_meta["url"] = entry[1]

                for k, v in directory_metadata.items():
                    if k not in media_meta:
                        media_meta[k] = v

                items.append(media_meta)
            elif isinstance(entry[1], dict):
                items.append(entry[1])

    # If no Type 3 items or direct dicts were found, but Type 2 dicts were present (and no error),
    # use Type 2 items (supports legacy test formats like [2, {...}])
    if not items and type2_entries:
        items = type2_entries

    if not items and error_messages:
        combined_err = " | ".join(error_messages)
        raise classify_error(combined_err)

    return items


async def inspect_url(
    url: str,
    proxy: str | None = None,
    cookies_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Simulate extraction and retrieve metadata items using gallery-dl."""
    cmd = [
        "gallery-dl",
        "--dump-json",
        "--simulate",
    ]

    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies_path and cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])

    cmd.append(url)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace")
        raise classify_error(err_msg)

    raw_stdout = stdout.decode("utf-8", errors="replace")
    items = parse_gallerydl_json(raw_stdout)
    if not items:
        # Check if stderr had warnings or error messages
        err_msg = stderr.decode("utf-8", errors="replace")
        if err_msg.strip():
            raise classify_error(err_msg)
        raise ExtractionError("gallery-dl found no media items for this URL")

    return items


async def download_items(
    url: str,
    output_dir: Path,
    selected_indices: list[int] | None = None,
    proxy: str | None = None,
    cookies_path: Path | None = None,
    progress_callback: Callable[..., Any] | None = None,
) -> list[Path]:
    """Download media items using gallery-dl while emitting progress events."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "gallery-dl",
        "-d",
        str(output_dir),
        "--no-mtime",
    ]

    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies_path and cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])

    # If selected_indices specified, format range if possible
    # (gallery-dl --range 1,3,5 where indices are 1-based)
    if selected_indices is not None and len(selected_indices) > 0:
        # gallery-dl --range uses 1-based indexing
        ranges = ",".join(str(i + 1) for i in sorted(selected_indices))
        cmd.extend(["--range", ranges])

    cmd.append(url)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    downloaded_lines: list[str] = []
    stderr_lines: list[str] = []

    async def read_stdout():
        if process.stdout:
            idx = 0
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    downloaded_lines.append(line)
                    idx += 1
                    if progress_callback:
                        res = progress_callback(
                            progress=min(round(idx * 15.0, 1), 95.0),
                            message=f"Downloaded item {idx}",
                        )
                        if asyncio.iscoroutine(res):
                            await res

    async def read_stderr():
        if process.stderr:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                stderr_lines.append(line.decode("utf-8", errors="replace"))

    await asyncio.gather(read_stdout(), read_stderr(), process.wait())

    if process.returncode != 0:
        err_msg = "".join(stderr_lines)
        raise classify_error(err_msg)

    # Recursively find all downloaded files in output_dir, excluding hidden, temporary, or cookie files
    files = [
        p
        for p in output_dir.rglob("*")
        if p.is_file()
        and not p.name.startswith(".")
        and not p.name.endswith(".part")
        and not p.name.startswith("client_cookies_")
    ]
    if not files:
        err_msg = "".join(stderr_lines).strip()
        if err_msg:
            raise classify_error(err_msg)
        raise ExtractionError("gallery-dl found no media files to download")

    return sorted(files)
