# Migration Guide: Auto-Update System

## Overview

This guide explains what changed and how to migrate to the new auto-update system.

## What Changed

### New Dependencies

```toml
# Added to pyproject.toml
"apscheduler>=3.10.0",
"beautifulsoup4>=4.12.0",  # was missing from deps
```

### New Files

```
backend/src/
├── download_tracker.py    # NEW: Tracks downloaded timestamps
├── scheduler.py           # NEW: Background scheduler
├── FEATURES.md           # NEW: Feature documentation
├── TESTING.md            # NEW: Testing guide
└── MIGRATION.md          # NEW: This file
```

### Modified Files

#### `config.py`
```python
# Changed
update_interval: int = 300  # Was 120, now 300 (5 minutes)

# Added
overlay_downsample_web: int = 4
overlay_downsample_high: int = 2
```

#### `utils.py`
```python
# Added functions
def get_latest_cached_timestamp(cache_dir, elevation)
def get_latest_cached_files(cache_dir, elevation_angles)
```

#### `api.py`
**Major changes:**

1. **Removed Background Tasks per Request**
   ```python
   # REMOVED
   async def check_for_updates()
   async def update_radar_data()
   ```

2. **Added Lifecycle Events**
   ```python
   # ADDED
   @app.on_event("startup")
   async def startup_event()
   
   @app.on_event("shutdown")
   async def shutdown_event()
   ```

3. **Modified `/api/radar/latest`**
   ```python
   # BEFORE: Downloads on every request
   async def get_latest_radar(background_tasks: BackgroundTasks, ...)
       elevation_files = await scraper.download_latest_multi_elevation()
   
   # AFTER: Uses cached data
   async def get_latest_radar(use_multi_elevation: bool = True)
       elevation_files = get_latest_cached_files(...)
   ```

4. **Added New Endpoints**
   ```python
   GET  /api/radar/status                 # Scheduler status
   GET  /api/radar/overlay/latest         # Leaflet-ready metadata
   GET  /api/radar/overlay/image/{timestamp}  # Optimized image
   POST /api/radar/update                 # Manual trigger (updated)
   ```

## Migration Steps

### 1. Install New Dependencies

```bash
cd backend
uv pip install -e .
```

### 2. Update Configuration (Optional)

If you have custom settings, update your `.env`:

```env
# Update if you had custom value
UPDATE_INTERVAL=300  # 5 minutes (was 120)

# Add new settings
OVERLAY_DOWNSAMPLE_WEB=4
OVERLAY_DOWNSAMPLE_HIGH=2
```

### 3. Clear Old Cache (Optional)

If you want a fresh start:

```bash
rm -rf cache/*
mkdir -p cache
```

### 4. Test the System

```bash
# Run integration test
python3 test_integration.py

# Start server
uvicorn src.api:app --reload

# In another terminal, check status
curl http://localhost:8000/api/radar/status
```

## Behavior Changes

### Before

| Aspect | Behavior |
|--------|----------|
| Data Updates | On-demand per request |
| First Request | Downloads data (slow) |
| Subsequent Requests | May download again |
| Duplicate Prevention | None |
| Background Tasks | Per-request background tasks |

### After

| Aspect | Behavior |
|--------|----------|
| Data Updates | Automatic every 5 minutes |
| First Request | May wait for initial download |
| Subsequent Requests | Serve from cache (fast) |
| Duplicate Prevention | Smart timestamp tracking |
| Background Tasks | Global scheduler service |

## API Response Changes

### `/api/radar/latest`

**No breaking changes**, but behavior differs:

**Before:**
- Downloads data on every call
- Returns newly downloaded data
- Slow (10-30 seconds)

**After:**
- Returns cached data
- Fast (< 1 second)
- May return 503 if no data cached yet

**Migration:** No code changes needed, but client should handle 503 gracefully.

### `/api/radar/update` (POST)

**Breaking change:**

**Before:**
```json
{
  "status": "Update triggered"
}
```

**After:**
```json
{
  "status": "Update triggered",
  "message": "Background update started. Check /api/radar/status for progress."
}
```

**Migration:** If parsing response, update to expect new `message` field.

## Client Code Migration

### Before (React Example)

```jsx
// Downloaded on every call, slow
const fetchData = async () => {
  const response = await fetch('/api/radar/latest');
  const data = await response.json();
  // ... use data
};
```

### After (React Example)

```jsx
// Fast, cached data
const fetchData = async () => {
  try {
    const response = await fetch('/api/radar/latest');
    if (response.status === 503) {
      // First load, data not ready yet
      console.log('Waiting for initial data...');
      return;
    }
    const data = await response.json();
    // ... use data
  } catch (error) {
    console.error('Failed to fetch radar data:', error);
  }
};
```

### Recommended Pattern

```jsx
import { useEffect, useState } from 'react';

function useRadarData() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('/api/radar/overlay/latest');
        
        if (response.status === 503) {
          setLoading(true);
          setError('Waiting for initial data download...');
          // Retry in 10 seconds
          setTimeout(fetchData, 10000);
          return;
        }
        
        const json = await response.json();
        setData(json);
        setLoading(false);
        setError(null);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };

    fetchData();
    
    // Poll for updates every 5 minutes
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    
    return () => clearInterval(interval);
  }, []);

  return { data, loading, error };
}
```

## Rollback Plan

If you need to rollback to the old system:

### 1. Revert Code Changes

```bash
git checkout HEAD~1 -- backend/src/api.py
git checkout HEAD~1 -- backend/src/config.py
```

### 2. Remove New Files

```bash
rm backend/src/download_tracker.py
rm backend/src/scheduler.py
```

### 3. Revert Dependencies

```bash
# Edit pyproject.toml
# Remove: "apscheduler>=3.10.0"
uv pip install -e .
```

### 4. Restart Server

```bash
uvicorn src.api:app --reload
```

## Benefits Summary

✅ **Improvements:**
- Faster API responses (cached data)
- Automatic updates without user action
- Duplicate prevention saves bandwidth
- Optimized images for web visualization
- Better resource utilization
- Production-ready scheduler

⚠️ **Trade-offs:**
- Initial request may get 503 (wait for data)
- Background process runs continuously
- Small memory overhead for scheduler

## Common Issues

### Issue: First request returns 503

**Expected behavior** on fresh install.

**Solution:** Wait 1-2 minutes for initial download.

### Issue: Updates not happening

**Check:**
```bash
# Logs should show:
INFO:src.scheduler:Starting radar update scheduler
INFO:src.scheduler:=== Starting scheduled radar update ===
```

**Solution:** Ensure scheduler started. Check logs for errors.

### Issue: Old endpoints not working

**Solution:** All old endpoints still work! New endpoints are additions.

## Questions?

- Check `FEATURES.md` for detailed feature documentation
- Check `TESTING.md` for testing procedures
- Check application logs for runtime issues

## Version Compatibility

| Component | Old Version | New Version | Compatible? |
|-----------|-------------|-------------|-------------|
| API endpoints | v0.1.0 | v0.1.0 | ✅ Yes |
| Response formats | - | - | ✅ Yes (with additions) |
| Configuration | - | - | ✅ Yes (backward compatible) |
| Client code | - | - | ⚠️ Handle 503 status |

✅ **No breaking changes for existing clients** (except initial 503 handling)

