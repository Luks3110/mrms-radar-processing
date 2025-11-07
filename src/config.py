"""Configuration management for the MRMS radar processor."""

from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # Paths
    cache_dir: Path = Path(__file__).parent.parent.parent / "cache"
    data_dir: Path = Path(__file__).parent.parent.parent / "data"
    assets_dir: Path = Path(__file__).parent.parent.parent / "assets"

    # MRMS configuration
    mrms_base_url: str = "https://mrms.ncep.noaa.gov/3DRefl"
    elevation_angles: List[float] = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50]
    use_elevation_subdirs: bool = True
    update_interval: int = 300  # seconds (5 minutes)
    download_timeout: int = 30  # seconds

    # Processing options
    max_cache_size: int = 50  # number of files to keep in cache
    rala_min_quality: float = 0.5  # QC threshold for valid data
    output_format: str = "png"  # png or json
    
    # Overlay/visualization settings
    overlay_downsample_web: int = 4  # Downsample factor for web display
    overlay_downsample_high: int = 2  # Downsample factor for high quality

    # Performance
    max_workers: int = 4
    chunk_size: int = 1000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra environment variables
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def get_elevation_url(self, elevation: float) -> str:
        """
        Get URL for specific elevation angle.
        
        Args:
            elevation: Elevation angle in km (e.g., 0.50, 1.00)
            
        Returns:
            Full URL to elevation directory
        """
        elevation_str = f"{elevation:05.2f}"
        return f"{self.mrms_base_url}/MergedReflectivityQC_{elevation_str}"


# Global settings instance
settings = Settings()

