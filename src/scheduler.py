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
            logger.warning("⚠️  Update already in progress, skipping this run")
            return

        self._is_running = True
        start_time = datetime.now()
        
        try:
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info("🔄 SCHEDULER: Starting scheduled radar update")
            logger.info(f"📅 Start time: {start_time.isoformat()}")
            logger.info(f"📁 Cache directory: {settings.cache_dir}")
            logger.info(f"🎯 Target elevations: {settings.elevation_angles}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            
            # Check for new data on the server
            logger.info("🔍 Fetching file list from MRMS server (elevation: 0.50 km)...")
            files_list = await self.scraper.fetch_file_list(elevation=0.50)
            
            if not files_list:
                logger.warning("⚠️  No files available on MRMS server")
                return

            logger.info(f"✅ Found {len(files_list)} files on server")
            latest_available = files_list[0]
            timestamp_str = format_timestamp(latest_available["timestamp"])
            
            logger.info(f"📊 Latest available timestamp: {timestamp_str}")
            logger.info(f"📦 Latest file: {latest_available.get('filename', 'N/A')}")
            logger.info(f"💾 File size: {latest_available.get('size', 'N/A')}")
            
            # Check if we already have this data
            tracked_timestamps = self.tracker.get_timestamps()
            logger.info(f"📋 Currently tracking {len(tracked_timestamps)} timestamps")
            
            if self.tracker.has_timestamp(timestamp_str):
                logger.info(f"✓ Timestamp {timestamp_str} already downloaded, skipping")
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
                return

            logger.info(f"🆕 New data available: {timestamp_str} - Starting download...")
            
            # Download multi-elevation data
            logger.info(f"⬇️  Downloading data for {len(settings.elevation_angles)} elevation angles...")
            for i, elevation in enumerate(settings.elevation_angles, 1):
                logger.info(f"  [{i}/{len(settings.elevation_angles)}] Elevation: {elevation} km")
            
            downloaded = await self.scraper.download_latest_multi_elevation(decompress=True)
            
            if downloaded:
                # Track the successful download
                self.tracker.add_timestamp(timestamp_str)
                elapsed = (datetime.now() - start_time).total_seconds()
                
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                logger.info("✅ SUCCESS: Radar data update completed")
                logger.info(f"📥 Downloaded files: {len(downloaded)}")
                logger.info(f"⏱️  Time elapsed: {elapsed:.2f} seconds")
                logger.info(f"🏷️  Tracked timestamp: {timestamp_str}")
                
                # Log individual files
                for elevation, filepath in downloaded.items():
                    file_size = filepath.stat().st_size / (1024 * 1024)  # MB
                    logger.info(f"  ✓ {elevation} km: {filepath.name} ({file_size:.2f} MB)")
                
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
            else:
                logger.warning("⚠️  No files were downloaded")
                logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
                
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.error(f"❌ ERROR: Failed to update radar data after {elapsed:.2f} seconds")
            logger.error(f"Error: {e}", exc_info=True)
            logger.error("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        finally:
            self._is_running = False
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"🏁 Scheduler update cycle complete (total time: {elapsed:.2f}s)\n")

    def start(self):
        """Start the background scheduler."""
        if self.scheduler is not None:
            logger.warning("Scheduler already started")
            return

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🚀 SCHEDULER STARTUP: Initializing radar update scheduler")
        logger.info(f"⏰ Update interval: {settings.update_interval}s ({settings.update_interval / 60:.1f} minutes)")
        logger.info(f"📁 Cache directory: {settings.cache_dir}")
        logger.info(f"🎯 Elevation angles: {settings.elevation_angles}")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
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
        logger.info("✅ Scheduler started successfully")
        logger.info("🔄 Triggering immediate initial update...")
        
        # Run immediately on startup
        asyncio.create_task(self.update_radar_data())

    def shutdown(self):
        """Shutdown the scheduler gracefully."""
        if self.scheduler is None:
            logger.warning("Scheduler not running")
            return

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🛑 SCHEDULER SHUTDOWN: Stopping radar update scheduler")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self.scheduler.shutdown(wait=True)
        self.scheduler = None
        logger.info("✅ Scheduler shutdown complete\n")

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

