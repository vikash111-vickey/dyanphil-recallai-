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
        default=Path(r"D:\prompteng\data"),
        description="Directory for application data, indices, and persistent state",
    )
    db_path: Path | None = Field(
        default=None,
        description="Path to the SQLite database file (defaults to <data_dir>/recall.db)",
    )
    folders_to_index: list[Path] = Field(
        default_factory=list,
        description="List of local folder paths to index",
    )

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        return self.data_dir / "recall.db"


settings = Settings()
