"""Application configuration module."""

import os
from pathlib import Path
from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Global application settings."""

    # Project directories
    BASE_DIR: Path = Field(
        default_factory=lambda: Path(
            os.getenv("BASE_DIR", str(Path(__file__).resolve().parent.parent.parent))
        )
    )
    COOKIES_DIR: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "COOKIES_DIR",
                str(
                    Path(os.getenv("BASE_DIR", str(Path(__file__).resolve().parent.parent.parent)))
                    / "cookies"
                ),
            )
        )
    )
    DOWNLOADS_DIR: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "DOWNLOADS_DIR",
                str(
                    Path(os.getenv("BASE_DIR", str(Path(__file__).resolve().parent.parent.parent)))
                    / "downloads"
                ),
            )
        )
    )

    # Proxy settings
    SOCKS5_PROXY: str | None = Field(default_factory=lambda: os.getenv("SOCKS5_PROXY", None))

    # YouTube player clients preference order
    YOUTUBE_PLAYER_CLIENTS: str = Field(
        default_factory=lambda: os.getenv("YOUTUBE_PLAYER_CLIENTS", "tv,ios,mweb,web")
    )

    # Storage cleanup TTL in minutes
    STORAGE_TTL_MINUTES: int = Field(
        default_factory=lambda: int(os.getenv("STORAGE_TTL_MINUTES", "60"))
    )

    def ensure_directories(self) -> None:
        """Create cookies and downloads directories if they do not exist."""
        self.COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        self.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
