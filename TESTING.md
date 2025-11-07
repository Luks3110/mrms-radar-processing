# Testing the Auto-Update Radar System

## Prerequisites

First, install the updated dependencies:

```bash
cd backend
uv pip install -e .
```

This will install the new `apscheduler` and `beautifulsoup4` packages.

## Quick Test

### 1. Run Integration Test

```bash
python3 test_integration.py
```

This tests:
- ✓ Download tracker functionality
- ✓ Scheduler initialization
- ✓ Utility functions
- ✓ API imports

Expected output:
```
============================================================
Integration Test for Auto-Update Radar System
============================================================

=== Testing Download Tracker ===
✓ Added timestamp: 20251107-200036
✓ Added timestamp: 20251107-195036
✓ Added timestamp: 20251107-194036
✓ Duplicate detection works
✓ Tracked timestamps: 3

=== Testing Utility Functions ===
⚠ No cached data found (this is OK for first run)
✓ Found cached files for 0 elevations

=== Testing Scheduler ===
Starting scheduler...
✓ Scheduler test complete

=== Testing API Imports ===
✓ API imports successful

============================================================
Test Summary
============================================================
Download Tracker................................ ✓ PASSED
Utility Functions............................... ✓ PASSED
Scheduler....................................... ✓ PASSED
API Imports..................................... ✓ PASSED

============================================================
✓ All tests passed!
```

### 2. Start the Server

```bash
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000
```

Watch the logs for:
```
INFO:src.api:Starting up MRMS Radar API...
INFO:src.scheduler:Starting radar update scheduler (interval: 300s)
INFO:src.scheduler:Scheduler started successfully
INFO:src.scheduler:=== Starting scheduled radar update ===
```

### 3. Test Endpoints

In a new terminal:

```bash
# Check system status
curl http://localhost:8000/api/radar/status | jq

# Wait for initial data download (1-2 minutes), then:

# Get latest overlay metadata
curl http://localhost:8000/api/radar/overlay/latest | jq

# Download the overlay image
curl http://localhost:8000/api/radar/overlay/image/20251107-200036?quality=web -o radar.png

# View the image
xdg-open radar.png  # Linux
# or
open radar.png  # macOS
```

## Testing Duplicate Detection

The scheduler automatically tracks downloaded timestamps. To test:

1. **First run**: Scheduler downloads new data
   - Check logs: "New data available: YYYYMMDD-HHMMSS"
   - Check logs: "Successfully downloaded and tracked N elevation files"

2. **Wait 5 minutes** for next scheduled run

3. **Second run**: Should skip if no new data
   - Check logs: "Timestamp YYYYMMDD-HHMMSS already downloaded, skipping"

4. **Manual test**:
   ```bash
   curl -X POST http://localhost:8000/api/radar/update
   # Should see duplicate detection in logs
   ```

## Testing Automatic Updates

### Monitor the Scheduler

```bash
# Check status every 30 seconds
watch -n 30 'curl -s http://localhost:8000/api/radar/status | jq ".scheduler"'
```

You'll see:
```json
{
  "running": true,
  "update_in_progress": false,
  "update_interval": 300,
  "next_run": "2025-11-07T20:05:00",
  "last_check": "2025-11-07T20:00:00Z",
  "tracked_timestamps": 5
}
```

### Watch for Updates

```bash
# Monitor cache directory
watch -n 10 'ls -lht cache/00_50/*.grib2 | head -5'
```

Every 5 minutes, if new data is available, you'll see new files appear.

## Testing Leaflet Integration

### Setup React Project

```bash
cd ../frontend  # or create a new React project
npm install react-leaflet leaflet
```

### Create Test Component

Use the example from `FEATURES.md`:

```jsx
import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, ImageOverlay } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

const API_BASE = 'http://localhost:8000';

function RadarMap() {
  const [overlayData, setOverlayData] = useState(null);

  useEffect(() => {
    fetchOverlay();
    const interval = setInterval(fetchOverlay, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const fetchOverlay = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/radar/overlay/latest`);
      const data = await response.json();
      setOverlayData(data);
    } catch (error) {
      console.error('Failed to fetch radar overlay:', error);
    }
  };

  if (!overlayData) return <div>Loading radar data...</div>;

  return (
    <MapContainer
      center={[37.5, -95]}
      zoom={5}
      style={{ height: '600px', width: '100%' }}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ImageOverlay
        url={`${API_BASE}${overlayData.image_url}?quality=web`}
        bounds={overlayData.bounds}
        opacity={0.7}
      />
    </MapContainer>
  );
}

export default RadarMap;
```

### Test in Browser

1. Start React dev server: `npm start`
2. Open browser to `http://localhost:3000`
3. Should see map with radar overlay
4. Check browser console for updates every 5 minutes

## Performance Testing

### Image Size Test

```bash
# Test different quality levels
curl http://localhost:8000/api/radar/overlay/image/20251107-200036?quality=web -o radar_web.png
curl http://localhost:8000/api/radar/overlay/image/20251107-200036?quality=high -o radar_high.png

# Check sizes
ls -lh radar_*.png
```

Expected sizes:
- `radar_web.png`: ~200-500 KB (1750x875 pixels)
- `radar_high.png`: ~800 KB - 2 MB (3500x1750 pixels)

### Load Test

```bash
# Concurrent requests (requires Apache Bench)
ab -n 100 -c 10 http://localhost:8000/api/radar/overlay/latest

# Should complete quickly due to caching
```

## Troubleshooting

### Problem: "No radar data available yet"

**Solution:**
1. Wait 1-2 minutes for initial download
2. Check scheduler logs
3. Manually trigger: `curl -X POST http://localhost:8000/api/radar/update`

### Problem: Scheduler not running

**Check logs:**
```bash
# Should see these on startup:
INFO:src.scheduler:Starting radar update scheduler
INFO:src.scheduler:Scheduler started successfully
```

**If missing:**
- Check for errors in startup logs
- Verify APScheduler is installed: `pip show apscheduler`

### Problem: Images not generating

**Check:**
1. GRIB2 files exist: `ls cache/00_50/*.grib2`
2. Permissions: `ls -la cache/`
3. Matplotlib backend: Should be 'Agg' (non-interactive)

### Problem: Download tracker not working

**Check:**
1. `cache/downloads.json` exists
2. File permissions: `ls -la cache/downloads.json`
3. Logs for "Added timestamp" messages

## Validation Checklist

- [ ] Dependencies installed (`uv pip install -e .`)
- [ ] Server starts without errors
- [ ] Scheduler initializes and runs
- [ ] Status endpoint returns valid JSON
- [ ] Initial data download completes
- [ ] Overlay endpoint returns metadata
- [ ] Overlay image generates successfully
- [ ] Duplicate detection prevents re-downloads
- [ ] Updates occur automatically every 5 minutes
- [ ] React + Leaflet integration works
- [ ] Images are cached on disk
- [ ] No memory leaks over 30+ minutes

## Success Criteria

✅ **The system is working correctly if:**

1. Server starts and scheduler initializes
2. Initial radar data downloads within 2 minutes
3. Status endpoint shows `"running": true`
4. Overlay endpoints return valid data/images
5. Subsequent updates detect duplicates
6. No errors in logs during normal operation
7. React app displays radar overlay on map
8. Automatic updates every 5 minutes (when new data available)

## Next Steps

Once testing is complete:
- Deploy to production environment
- Set up monitoring/alerting for scheduler failures
- Configure CORS for production frontend domain
- Consider adding Redis for distributed caching
- Add metrics/analytics endpoints

