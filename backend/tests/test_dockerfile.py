"""Tests for Dockerfile configuration, ensuring compliance with OCI fully qualified image names (FQIN).

Prevents short-name resolution errors in Podman, Buildah, and strict container runtimes.
"""

from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"

KNOWN_REGISTRIES = (
    "docker.io/",
    "ghcr.io/",
    "quay.io/",
    "gcr.io/",
    "registry.k8s.io/",
    "mcr.microsoft.com/",
    "public.ecr.aws/",
)


def is_fully_qualified_image(image_ref: str) -> bool:
    """Return True if image_ref begins with a known registry or domain containing a dot or port."""
    if any(image_ref.startswith(reg) for reg in KNOWN_REGISTRIES):
        return True
    first_part = image_ref.split("/")[0]
    return "." in first_part or ":" in first_part or first_part == "localhost"


def test_dockerfile_exists():
    """Verify Dockerfile exists at the repository root."""
    assert DOCKERFILE_PATH.is_file(), f"Dockerfile not found at {DOCKERFILE_PATH}"


def test_dockerfile_all_from_images_are_fully_qualified():
    """Verify that all base images in FROM directives are fully qualified.

    Unqualified short-names (e.g. 'oven/bun:1-slim' or 'python:3.12-slim') fail in Podman
    and Buildah when unqualified-search-registries is not configured.
    """
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    stages = set()
    from_statements = []

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = re.match(
            r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+[aA][sS]\s+(\S+))?",
            stripped,
        )
        if match:
            image_ref = match.group(1)
            stage_alias = match.group(2)
            from_statements.append((line_num, image_ref, stage_alias))
            if stage_alias:
                stages.add(stage_alias)

    assert len(from_statements) >= 2, "Expected at least 2 stages in multi-stage Dockerfile"

    for line_num, image_ref, stage_alias in from_statements:
        # If it references a previous stage, that's valid
        if image_ref in stages:
            continue

        assert is_fully_qualified_image(image_ref), (
            f"Line {line_num} in Dockerfile uses an unqualified short-name '{image_ref}'. "
            f"Must use a fully qualified image reference (e.g., 'docker.io/{image_ref}') "
            f"to support Podman/Buildah without short-name resolution errors."
        )

    # Explicitly check required stages
    images = [img for _, img, _ in from_statements]
    assert "docker.io/oven/bun:1-slim" in images
    assert "docker.io/library/python:3.12-slim" in images


def test_dockerfile_copy_from_directives_are_valid():
    """Verify that COPY --from directives reference either a valid build stage or a fully qualified image."""
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    stages = set()
    for line in lines:
        stripped = line.strip()
        match = re.match(
            r"^FROM\s+(?:--platform=\S+\s+)?\S+(?:\s+[aA][sS]\s+(\S+))?",
            stripped,
        )
        if match and match.group(1):
            stages.add(match.group(1))

    copy_from_pattern = re.compile(r"^COPY\s+--from=(\S+)")
    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()
        match = copy_from_pattern.match(stripped)
        if match:
            source = match.group(1)
            if source in stages:
                continue
            assert is_fully_qualified_image(source), (
                f"Line {line_num} in Dockerfile has COPY --from={source} which is neither a known "
                f"build stage ({stages}) nor a fully qualified image reference."
            )
