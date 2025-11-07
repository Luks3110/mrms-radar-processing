"""Utility functions for MRMS radar processing."""

import re
import gzip
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def format_elevation_angle(elevation: float) -> str:
    """
    Format elevation angle for URL/directory naming.
    
    Args:
        elevation: Elevation angle in km (e.g., 0.50, 1.00)
        
    Returns:
        Formatted string (e.g., '00_50', '01_00')
    """
    return f"{elevation:05.2f}".replace(".", "_")


def parse_elevation_from_filename(filename: str) -> Optional[float]:
    """
    Extract elevation angle from MRMS filename.
    
    Args:
        filename: MRMS filename string
        
    Returns:
        Elevation angle or None if parsing fails
    """
    pattern = r"MergedReflectivityQC_(\d{2})_(\d{2})_"
    match = re.search(pattern, filename)
    
    if not match:
        return None
    
    try:
        degrees = int(match.group(1))
        fraction = int(match.group(2))
        return float(f"{degrees}.{fraction}")
    except ValueError:
        logger.error(f"Failed to parse elevation from: {filename}")
        return None


def parse_mrms_filename(filename: str) -> Optional[datetime]:
    """
    Parse timestamp from MRMS filename.
    
    Example: MRMS_MergedReflectivityQC_02.50_20251107-200036.grib2.gz
    Returns: datetime(2025, 11, 7, 20, 0, 36)
    
    Args:
        filename: MRMS filename string
        
    Returns:
        datetime object or None if parsing fails
    """
    # Pattern to handle elevation angles with periods (e.g., 02.50)
    pattern = r"MRMS_MergedReflectivityQC_\d{2}\.\d{2}_(\d{8})-(\d{6})\.grib2"
    match = re.search(pattern, filename)
    
    if not match:
        return None
    
    date_str, time_str = match.groups()
    try:
        return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
    except ValueError:
        logger.error(f"Failed to parse datetime from: {filename}")
        return None


def decompress_grib2(input_path: Path, output_path: Optional[Path] = None) -> Path:
    """
    Decompress a .grib2.gz file.
    
    Args:
        input_path: Path to compressed .grib2.gz file
        output_path: Optional output path. If None, removes .gz extension
        
    Returns:
        Path to decompressed file
    """
    if output_path is None:
        output_path = input_path.with_suffix("")  # Remove .gz
    
    logger.info(f"Decompressing {input_path} to {output_path}")
    
    with gzip.open(input_path, "rb") as f_in:
        with open(output_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    return output_path


def format_timestamp(dt: datetime) -> str:
    """
    Format datetime for MRMS filename.
    
    Args:
        dt: datetime object
        
    Returns:
        Formatted string like "20251107-200036"
    """
    return dt.strftime("%Y%m%d-%H%M%S")


def dbz_to_color(dbz_value: float) -> Tuple[int, int, int, int]:
    """
    Convert dBZ reflectivity value to RGBA color.
    
    Standard weather radar color scale:
    - < 5 dBZ: Transparent (no precipitation)
    - 5-15: Light blue (drizzle)
    - 15-30: Green (light rain)
    - 30-40: Yellow (moderate rain)
    - 40-50: Orange (heavy rain)
    - 50-60: Red (very heavy rain)
    - > 60: Magenta (extreme/hail)
    
    Args:
        dbz_value: Reflectivity in dBZ
        
    Returns:
        RGBA tuple (R, G, B, A) with values 0-255
    """
    if dbz_value < 5:
        return (0, 0, 0, 0)  # Transparent
    elif dbz_value < 15:
        return (100, 200, 255, 200)  # Light blue
    elif dbz_value < 30:
        return (50, 200, 50, 220)  # Green
    elif dbz_value < 40:
        return (255, 255, 0, 240)  # Yellow
    elif dbz_value < 50:
        return (255, 150, 0, 255)  # Orange
    elif dbz_value < 60:
        return (255, 0, 0, 255)  # Red
    else:
        return (200, 0, 200, 255)  # Magenta


def cleanup_old_files(directory: Path, max_files: int = 50) -> int:
    """
    Remove oldest files if directory exceeds max_files.
    
    Args:
        directory: Directory to clean
        max_files: Maximum number of files to keep
        
    Returns:
        Number of files removed
    """
    files = sorted(directory.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if len(files) <= max_files:
        return 0
    
    files_to_remove = files[max_files:]
    for file in files_to_remove:
        try:
            file.unlink()
            logger.info(f"Removed old file: {file.name}")
        except Exception as e:
            logger.error(f"Failed to remove {file.name}: {e}")
    
    return len(files_to_remove)


def validate_grib2_file(file_path: Path) -> bool:
    """
    Validate that a file is a valid GRIB2 file.
    
    Args:
        file_path: Path to GRIB2 file
        
    Returns:
        True if valid, False otherwise
    """
    if not file_path.exists():
        return False
    
    # GRIB2 files start with "GRIB" magic bytes
    try:
        with open(file_path, "rb") as f:
            magic = f.read(4)
            return magic == b"GRIB"
    except Exception as e:
        logger.error(f"Error validating {file_path}: {e}")
        return False


def get_latest_cached_timestamp(cache_dir: Path, elevation: float = 0.50) -> Optional[str]:
    """
    Get the timestamp of the most recent cached file.
    
    Args:
        cache_dir: Cache directory to search
        elevation: Elevation angle subdirectory
        
    Returns:
        Timestamp string in format YYYYMMDD-HHMMSS, or None if no files found
    """
    from .config import settings
    
    # Build path based on elevation subdirs setting
    if settings.use_elevation_subdirs:
        search_dir = cache_dir / format_elevation_angle(elevation)
    else:
        search_dir = cache_dir
    
    if not search_dir.exists():
        return None
    
    # Find all .grib2 files
    grib_files = sorted(
        search_dir.glob("*.grib2"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    
    if not grib_files:
        return None
    
    # Parse timestamp from most recent file
    latest_file = grib_files[0]
    timestamp = parse_mrms_filename(latest_file.name)
    
    if timestamp:
        return format_timestamp(timestamp)
    
    return None


def get_latest_cached_files(cache_dir: Path, elevation_angles: list) -> dict:
    """
    Get the most recent cached files for all elevation angles.
    
    Args:
        cache_dir: Cache directory to search
        elevation_angles: List of elevation angles to check
        
    Returns:
        Dict mapping elevation angle to file path
    """
    from .config import settings
    
    result = {}
    
    for elevation in elevation_angles:
        # Build path based on elevation subdirs setting
        if settings.use_elevation_subdirs:
            search_dir = cache_dir / format_elevation_angle(elevation)
        else:
            search_dir = cache_dir
        
        if not search_dir.exists():
            continue
        
        # Find all .grib2 files
        grib_files = sorted(
            search_dir.glob("*.grib2"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        if grib_files:
            result[elevation] = grib_files[0]
    
    return result

