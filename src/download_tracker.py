"""Download tracking to prevent duplicate downloads."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Set
from threading import Lock

logger = logging.getLogger(__name__)


class DownloadTracker:
    """Track downloaded radar data timestamps to prevent duplicates."""

    def __init__(self, cache_dir: Path, max_timestamps: int = 100):
        """
        Initialize download tracker.
        
        Args:
            cache_dir: Directory for cache files
            max_timestamps: Maximum number of timestamps to keep in history
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tracker_file = self.cache_dir / "downloads.json"
        self.max_timestamps = max_timestamps
        self._lock = Lock()
        self._timestamps: Set[str] = set()
        self._last_check: str = ""
        self._load()

    def _load(self) -> None:
        """Load tracking data from file."""
        if not self.tracker_file.exists():
            logger.info(f"No tracker file found at {self.tracker_file}, starting fresh")
            self._timestamps = set()
            self._last_check = datetime.utcnow().isoformat()
            self._save()
            return

        try:
            with open(self.tracker_file, "r") as f:
                data = json.load(f)
                self._timestamps = set(data.get("timestamps", []))
                self._last_check = data.get("last_check", datetime.utcnow().isoformat())
                logger.info(f"Loaded {len(self._timestamps)} tracked timestamps")
        except Exception as e:
            logger.error(f"Failed to load tracker file: {e}")
            self._timestamps = set()
            self._last_check = datetime.utcnow().isoformat()

    def _save(self) -> None:
        """Save tracking data to file."""
        try:
            data = {
                "timestamps": sorted(list(self._timestamps), reverse=True)[:self.max_timestamps],
                "last_check": self._last_check
            }
            with open(self.tracker_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved tracker with {len(data['timestamps'])} timestamps")
        except Exception as e:
            logger.error(f"Failed to save tracker file: {e}")

    def has_timestamp(self, timestamp: str) -> bool:
        """
        Check if a timestamp has already been downloaded.
        
        Args:
            timestamp: Timestamp string in format YYYYMMDD-HHMMSS
            
        Returns:
            True if timestamp exists in history
        """
        with self._lock:
            return timestamp in self._timestamps

    def add_timestamp(self, timestamp: str) -> None:
        """
        Add a timestamp to the download history.
        
        Args:
            timestamp: Timestamp string in format YYYYMMDD-HHMMSS
        """
        with self._lock:
            if timestamp in self._timestamps:
                logger.debug(f"Timestamp {timestamp} already tracked")
                return
            
            self._timestamps.add(timestamp)
            self._last_check = datetime.utcnow().isoformat()
            self.cleanup_old()
            self._save()
            logger.info(f"Added timestamp {timestamp} to tracker")

    def cleanup_old(self) -> int:
        """
        Remove oldest timestamps if we exceed max_timestamps.
        
        Returns:
            Number of timestamps removed
        """
        if len(self._timestamps) <= self.max_timestamps:
            return 0

        # Sort timestamps and keep only the most recent max_timestamps
        sorted_timestamps = sorted(list(self._timestamps), reverse=True)
        keep = set(sorted_timestamps[:self.max_timestamps])
        removed = self._timestamps - keep
        
        self._timestamps = keep
        
        logger.info(f"Cleaned up {len(removed)} old timestamps")
        return len(removed)

    def get_timestamps(self) -> List[str]:
        """
        Get all tracked timestamps.
        
        Returns:
            List of timestamp strings, sorted newest first
        """
        with self._lock:
            return sorted(list(self._timestamps), reverse=True)

    def get_last_check(self) -> str:
        """
        Get the last check timestamp.
        
        Returns:
            ISO format timestamp string
        """
        return self._last_check

    def clear(self) -> None:
        """Clear all tracked timestamps."""
        with self._lock:
            self._timestamps.clear()
            self._last_check = datetime.utcnow().isoformat()
            self._save()
            logger.info("Cleared all tracked timestamps")

