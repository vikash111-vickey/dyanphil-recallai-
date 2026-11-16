from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(
        default=Path("data"),
        description="Directory for application data, indices, and persistent state",
    )
    db_path: Path = Field(
        default=Path("data/dyanphil.db"),
        description="Path to the SQLite database file",
    )
    folders_to_index: list[Path] = Field(
        default_factory=list,
        description="List of local folder paths to index",
    )


settings = Settings()
