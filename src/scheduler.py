"""Background scheduler for automatic radar data updates."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings
from .scraper import MRMSScraper
from .download_tracker import DownloadTracker
from .utils import format_timestamp, parse_mrms_filename

logger = logging.getLogger(__name__)


class RadarScheduler:
    """Scheduler for automatic radar data updates."""

    def __init__(self):
        """Initialize the radar update scheduler."""
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.scraper = MRMSScraper()
        self.tracker = DownloadTracker(settings.cache_dir)
        self._is_running = False

    async def update_radar_data(self):
        """
        Download latest radar data for all elevations.
        
        This is the main scheduled task that runs periodically.
        """
        if self._is_running:
            logger.warning("Update already in progress, skipping this run")
            return

        self._is_running = True
        try:
            logger.info("=== Starting scheduled radar update ===")
            
            # Check for new data on the server
            files_list = await self.scraper.fetch_file_list(elevation=0.50)
            
            if not files_list:
                logger.warning("No files available on MRMS server")
                return

            latest_available = files_list[0]
            timestamp_str = format_timestamp(latest_available["timestamp"])
            
            # Check if we already have this data
            if self.tracker.has_timestamp(timestamp_str):
                logger.info(f"Timestamp {timestamp_str} already downloaded, skipping")
                return

            logger.info(f"New data available: {timestamp_str}")
            
            # Download multi-elevation data
            downloaded = await self.scraper.download_latest_multi_elevation(decompress=True)
            
            if downloaded:
                # Track the successful download
                self.tracker.add_timestamp(timestamp_str)
                logger.info(f"Successfully downloaded and tracked {len(downloaded)} elevation files")
            else:
                logger.warning("No files were downloaded")
                
        except Exception as e:
            logger.error(f"Failed to update radar data: {e}", exc_info=True)
        finally:
            self._is_running = False
            logger.info("=== Scheduled radar update complete ===")

    def start(self):
        """Start the background scheduler."""
        if self.scheduler is not None:
            logger.warning("Scheduler already started")
            return

        logger.info(f"Starting radar update scheduler (interval: {settings.update_interval}s)")
        
        self.scheduler = AsyncIOScheduler()
        
        # Schedule the update task
        self.scheduler.add_job(
            self.update_radar_data,
            trigger=IntervalTrigger(seconds=settings.update_interval),
            id="radar_update",
            name="Radar Data Update",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
        )
        
        self.scheduler.start()
        logger.info("Scheduler started successfully")
        
        # Run immediately on startup
        asyncio.create_task(self.update_radar_data())

    def shutdown(self):
        """Shutdown the scheduler gracefully."""
        if self.scheduler is None:
            logger.warning("Scheduler not running")
            return

        logger.info("Shutting down radar update scheduler")
        self.scheduler.shutdown(wait=True)
        self.scheduler = None
        logger.info("Scheduler shutdown complete")

    def get_status(self) -> dict:
        """
        Get current scheduler status.
        
        Returns:
            Dictionary with scheduler status information
        """
        if self.scheduler is None:
            return {
                "running": False,
                "message": "Scheduler not started"
            }

        jobs = self.scheduler.get_jobs()
        next_run = None
        
        if jobs:
            next_run_time = jobs[0].next_run_time
            if next_run_time:
                next_run = next_run_time.isoformat()

        return {
            "running": self.scheduler.running,
            "update_in_progress": self._is_running,
            "update_interval": settings.update_interval,
            "next_run": next_run,
            "last_check": self.tracker.get_last_check(),
            "tracked_timestamps": len(self.tracker.get_timestamps()),
        }


# Global scheduler instance
_scheduler: Optional[RadarScheduler] = None


def get_scheduler() -> RadarScheduler:
    """
    Get the global scheduler instance.
    
    Returns:
        RadarScheduler instance
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = RadarScheduler()
    return _scheduler


async def start_scheduler():
    """Start the global scheduler (called on app startup)."""
    scheduler = get_scheduler()
    scheduler.start()


async def shutdown_scheduler():
    """Shutdown the global scheduler (called on app shutdown)."""
    scheduler = get_scheduler()
    scheduler.shutdown()

