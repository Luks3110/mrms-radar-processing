"""MRMS data scraper for downloading GRIB2 files."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import urljoin, unquote

import aiohttp
from bs4 import BeautifulSoup

from .config import settings
from .utils import parse_mrms_filename, decompress_grib2, cleanup_old_files, format_elevation_angle

logger = logging.getLogger(__name__)


class MRMSScraper:
    """Scraper for MRMS radar data files."""

    def __init__(self, base_url: Optional[str] = None, cache_dir: Optional[Path] = None):
        """
        Initialize MRMS scraper.
        
        Args:
            base_url: MRMS server URL (defaults to settings)
            cache_dir: Directory for caching files (defaults to settings)
        """
        self.base_url = base_url or settings.mrms_base_url
        self.cache_dir = cache_dir or settings.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Headers to avoid 403 Forbidden errors
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

    def get_cache_path(self, elevation: float) -> Path:
        """
        Get cache directory for specific elevation angle.
        
        Args:
            elevation: Elevation angle in km
            
        Returns:
            Path to cache directory for this elevation
        """
        if settings.use_elevation_subdirs:
            subdir = self.cache_dir / format_elevation_angle(elevation)
            subdir.mkdir(parents=True, exist_ok=True)
            return subdir
        return self.cache_dir

    async def fetch_file_list(self, elevation: Optional[float] = None) -> List[dict]:
        """
        Fetch list of available GRIB2 files from MRMS server.
        
        Args:
            elevation: Specific elevation angle to fetch (uses base_url if None)
        
        Returns:
            List of dicts with 'filename', 'url', 'timestamp', 'size', 'elevation'
        """
        if elevation is not None:
            url = settings.get_elevation_url(elevation)
        else:
            url = self.base_url
            
        logger.info(f"Fetching file list from {url}")
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=settings.download_timeout)
                ) as response:
                    response.raise_for_status()
                    html = await response.text()
            except Exception as e:
                logger.error(f"Failed to fetch file list from {url}: {e}")
                raise

        # Parse HTML directory listing
        soup = BeautifulSoup(html, "html.parser")
        files = []
        
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if ".grib2.gz" in href and "latest" not in href:
                filename = unquote(href)  # URL decode the filename
                timestamp = parse_mrms_filename(filename)
                
                if timestamp:
                    files.append({
                        "filename": filename,
                        "url": urljoin(url + "/", href),
                        "timestamp": timestamp,
                        "size": link.find_next("td").text if link.find_next("td") else "unknown",
                        "elevation": elevation
                    })
        
        # Sort by timestamp, newest first
        files.sort(key=lambda x: x["timestamp"], reverse=True)
        logger.info(f"Found {len(files)} GRIB2 files at elevation {elevation}")
        
        return files

    async def fetch_file_list_multi_elevation(
        self,
        elevation_angles: Optional[List[float]] = None
    ) -> Dict[float, List[dict]]:
        """
        Fetch file lists from multiple elevation angles.
        
        Args:
            elevation_angles: List of elevation angles to fetch (defaults to settings)
        
        Returns:
            Dict mapping elevation angle to list of file info dicts
        """
        angles = elevation_angles or settings.elevation_angles
        logger.info(f"Fetching file lists for {len(angles)} elevation angles")
        
        # Fetch all elevations concurrently
        tasks = [self.fetch_file_list(elevation=angle) for angle in angles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Organize results by elevation
        file_lists = {}
        for angle, result in zip(angles, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to fetch elevation {angle}: {result}")
                file_lists[angle] = []
            else:
                file_lists[angle] = result
        
        return file_lists

    async def download_file(self, url: str, output_path: Path) -> Path:
        """
        Download a GRIB2 file from MRMS server.
        
        Args:
            url: URL of file to download
            output_path: Where to save the file
            
        Returns:
            Path to downloaded file
        """
        logger.info(f"Downloading {url}")
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=settings.download_timeout)
                ) as response:
                    response.raise_for_status()
                    
                    with open(output_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            
            except Exception as e:
                logger.error(f"Failed to download {url}: {e}")
                if output_path.exists():
                    output_path.unlink()  # Clean up partial download
                raise
        
        logger.info(f"Downloaded to {output_path} ({output_path.stat().st_size} bytes)")
        return output_path

    async def get_latest_file(self, decompress: bool = True, elevation: Optional[float] = None) -> Optional[Path]:
        """
        Download the latest GRIB2 file.
        
        Args:
            decompress: Whether to decompress the .gz file
            elevation: Specific elevation angle to download (uses base_url if None)
            
        Returns:
            Path to downloaded (and optionally decompressed) file
        """
        files = await self.fetch_file_list(elevation=elevation)
        
        if not files:
            logger.warning(f"No files found on MRMS server for elevation {elevation}")
            return None
        
        latest = files[0]
        logger.info(f"Latest file: {latest['filename']} from {latest['timestamp']}")
        
        # Determine cache directory
        if elevation is not None:
            cache_path = self.get_cache_path(elevation)
        else:
            cache_path = self.cache_dir
        
        # Download compressed file
        compressed_path = cache_path / latest["filename"]
        await self.download_file(latest["url"], compressed_path)
        
        if decompress:
            # Decompress to .grib2
            decompressed_path = decompress_grib2(compressed_path)
            logger.info(f"Decompressed to {decompressed_path}")
            
            # Optionally remove compressed file to save space
            # compressed_path.unlink()
            
            return decompressed_path
        
        return compressed_path

    async def download_latest_multi_elevation(
        self,
        elevation_angles: Optional[List[float]] = None,
        decompress: bool = True
    ) -> Dict[float, Path]:
        """
        Download the latest file for each elevation angle with matching timestamps.
        
        Args:
            elevation_angles: List of elevation angles to download (defaults to settings)
            decompress: Whether to decompress files
            
        Returns:
            Dict mapping elevation angle to downloaded file path
        """
        angles = elevation_angles or settings.elevation_angles
        logger.info(f"Downloading latest files for {len(angles)} elevation angles")
        
        # Fetch file lists for all elevations
        file_lists = await self.fetch_file_list_multi_elevation(angles)
        
        # Find the most recent common timestamp across all elevations
        # For simplicity, use the latest timestamp from the lowest elevation
        if not file_lists or not file_lists.get(angles[0]):
            logger.error("No files available for lowest elevation")
            return {}
        
        # Get target timestamp from lowest elevation
        target_timestamp = file_lists[angles[0]][0]["timestamp"]
        logger.info(f"Target timestamp for multi-elevation download: {target_timestamp}")
        
        # Download files for each elevation
        downloaded = {}
        for angle in angles:
            if angle not in file_lists or not file_lists[angle]:
                logger.warning(f"No files available for elevation {angle}")
                continue
            
            # Find file closest to target timestamp
            files_at_angle = file_lists[angle]
            matching_file = None
            min_time_diff = None
            
            for file_info in files_at_angle:
                time_diff = abs((file_info["timestamp"] - target_timestamp).total_seconds())
                if min_time_diff is None or time_diff < min_time_diff:
                    min_time_diff = time_diff
                    matching_file = file_info
            
            if matching_file is None:
                logger.warning(f"No matching file for elevation {angle}")
                continue
            
            # Check if already downloaded
            cache_path = self.get_cache_path(angle)
            compressed_path = cache_path / matching_file["filename"]
            
            if compressed_path.exists():
                logger.info(f"File already exists: {compressed_path.name}")
                if decompress:
                    decompressed_path = compressed_path.with_suffix("")
                    if not decompressed_path.exists():
                        decompressed_path = decompress_grib2(compressed_path)
                    downloaded[angle] = decompressed_path
                else:
                    downloaded[angle] = compressed_path
                continue
            
            # Download file
            try:
                await self.download_file(matching_file["url"], compressed_path)
                
                if decompress:
                    decompressed_path = decompress_grib2(compressed_path)
                    downloaded[angle] = decompressed_path
                else:
                    downloaded[angle] = compressed_path
                    
            except Exception as e:
                logger.error(f"Failed to download elevation {angle}: {e}")
                continue
        
        logger.info(f"Successfully downloaded {len(downloaded)} elevation angles")
        
        # Cleanup old files in each elevation directory
        for angle in downloaded.keys():
            cache_path = self.get_cache_path(angle)
            cleanup_old_files(cache_path, settings.max_cache_size)
        
        return downloaded

    async def download_multiple(
        self,
        count: int = 5,
        decompress: bool = True
    ) -> List[Path]:
        """
        Download multiple recent GRIB2 files.
        
        Args:
            count: Number of files to download
            decompress: Whether to decompress files
            
        Returns:
            List of paths to downloaded files
        """
        files = await self.fetch_file_list()
        
        if not files:
            return []
        
        # Download up to 'count' most recent files
        to_download = files[:count]
        downloaded = []
        
        for file_info in to_download:
            try:
                compressed_path = self.cache_dir / file_info["filename"]
                
                # Skip if already downloaded
                if compressed_path.exists():
                    logger.info(f"File already exists: {compressed_path.name}")
                    if decompress:
                        decompressed_path = compressed_path.with_suffix("")
                        if not decompressed_path.exists():
                            decompressed_path = decompress_grib2(compressed_path)
                        downloaded.append(decompressed_path)
                    else:
                        downloaded.append(compressed_path)
                    continue
                
                await self.download_file(file_info["url"], compressed_path)
                
                if decompress:
                    decompressed_path = decompress_grib2(compressed_path)
                    downloaded.append(decompressed_path)
                else:
                    downloaded.append(compressed_path)
                    
            except Exception as e:
                logger.error(f"Failed to download {file_info['filename']}: {e}")
                continue
        
        # Cleanup old files
        cleanup_old_files(self.cache_dir, settings.max_cache_size)
        
        return downloaded

    def get_cached_files(self) -> List[Path]:
        """
        Get list of cached GRIB2 files.
        
        Returns:
            List of paths to cached .grib2 files
        """
        files = sorted(
            self.cache_dir.glob("*.grib2"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        return files


# Convenience function
async def fetch_latest_radar() -> Optional[Path]:
    """
    Fetch the latest radar file.
    
    Returns:
        Path to latest GRIB2 file
    """
    scraper = MRMSScraper()
    return await scraper.get_latest_file()

