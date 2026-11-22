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
    fastembed_cache_path: Path = Field(
        default=Path(r"D:\cache\models"),
        validation_alias="FASTEMBED_CACHE_PATH",
        description="Directory for caching downloaded FastEmbed models",
    )
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        validation_alias="EMBEDDING_MODEL",
        description="FastEmbed model name for semantic text embeddings",
    )

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        return self.data_dir / "recall.db"


settings = Settings()
