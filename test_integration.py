#!/usr/bin/env python3
"""
Integration test for the auto-update radar system.

This script tests:
1. Scheduler initialization
2. Download tracking
3. Duplicate detection
4. API endpoints
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import settings
from src.scheduler import RadarScheduler
from src.download_tracker import DownloadTracker
from src.utils import get_latest_cached_timestamp, get_latest_cached_files


async def test_download_tracker():
    """Test the download tracker."""
    print("\n=== Testing Download Tracker ===")
    
    tracker = DownloadTracker(settings.cache_dir, max_timestamps=5)
    
    # Test adding timestamps
    test_timestamps = [
        "20251107-200036",
        "20251107-195036",
        "20251107-194036",
    ]
    
    for ts in test_timestamps:
        tracker.add_timestamp(ts)
        print(f"✓ Added timestamp: {ts}")
    
    # Test duplicate detection
    if tracker.has_timestamp("20251107-200036"):
        print("✓ Duplicate detection works")
    else:
        print("✗ Duplicate detection failed")
        return False
    
    # Test getting timestamps
    all_ts = tracker.get_timestamps()
    print(f"✓ Tracked timestamps: {len(all_ts)}")
    
    return True


async def test_scheduler():
    """Test the scheduler initialization."""
    print("\n=== Testing Scheduler ===")
    
    scheduler = RadarScheduler()
    
    # Get status before starting
    status = scheduler.get_status()
    print(f"Status before start: running={status['running']}")
    
    # Start scheduler
    print("Starting scheduler...")
    scheduler.start()
    
    # Wait a moment
    await asyncio.sleep(2)
    
    # Get status after starting
    status = scheduler.get_status()
    print(f"Status after start: running={status['running']}")
    print(f"Update interval: {status['update_interval']}s")
    print(f"Next run: {status.get('next_run', 'N/A')}")
    
    # Shutdown
    print("Shutting down scheduler...")
    scheduler.shutdown()
    
    print("✓ Scheduler test complete")
    return True


def test_utils():
    """Test utility functions."""
    print("\n=== Testing Utility Functions ===")
    
    # Test getting latest cached timestamp
    latest = get_latest_cached_timestamp(settings.cache_dir, elevation=0.50)
    if latest:
        print(f"✓ Latest cached timestamp: {latest}")
    else:
        print("⚠ No cached data found (this is OK for first run)")
    
    # Test getting latest cached files
    files = get_latest_cached_files(settings.cache_dir, settings.elevation_angles)
    print(f"✓ Found cached files for {len(files)} elevations")
    
    return True


async def test_api_imports():
    """Test that API module imports correctly."""
    print("\n=== Testing API Imports ===")
    
    try:
        from src.api import app, startup_event, shutdown_event
        print("✓ API imports successful")
        print(f"✓ App name: {app.title}")
        return True
    except Exception as e:
        print(f"✗ API import failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Integration Test for Auto-Update Radar System")
    print("=" * 60)
    
    results = []
    
    # Test 1: Download Tracker
    try:
        result = await test_download_tracker()
        results.append(("Download Tracker", result))
    except Exception as e:
        print(f"✗ Download tracker test failed: {e}")
        results.append(("Download Tracker", False))
    
    # Test 2: Utility Functions
    try:
        result = test_utils()
        results.append(("Utility Functions", result))
    except Exception as e:
        print(f"✗ Utils test failed: {e}")
        results.append(("Utility Functions", False))
    
    # Test 3: Scheduler
    try:
        result = await test_scheduler()
        results.append(("Scheduler", result))
    except Exception as e:
        print(f"✗ Scheduler test failed: {e}")
        results.append(("Scheduler", False))
    
    # Test 4: API Imports
    try:
        result = await test_api_imports()
        results.append(("API Imports", result))
    except Exception as e:
        print(f"✗ API import test failed: {e}")
        results.append(("API Imports", False))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name:.<40} {status}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed!")
        print("\nNext steps:")
        print("1. Start the server: uvicorn src.api:app --reload")
        print("2. Check status: curl http://localhost:8000/api/radar/status")
        print("3. Get overlay: curl http://localhost:8000/api/radar/overlay/latest")
    else:
        print("✗ Some tests failed. Please check the output above.")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

