# New Features: Auto-Update & Leaflet Integration

## Overview

The MRMS Radar API now includes:
- **Automatic Background Updates**: Data fetches every 5 minutes
- **Duplicate Detection**: Smart tracking to avoid re-downloading existing data
- **Leaflet-Optimized Endpoints**: Ready-to-use overlay images for React + Leaflet

## Automatic Updates

### How It Works

1. **Background Scheduler**: APScheduler runs independently of API requests
2. **Smart Downloads**: Checks for new data every 5 minutes (configurable)
3. **Duplicate Prevention**: Tracks downloaded timestamps to avoid redundant downloads
4. **Multi-Elevation**: Downloads all configured elevation angles

### Configuration

Set in `.env` or environment variables:

```env
UPDATE_INTERVAL=300  # seconds (5 minutes)
OVERLAY_DOWNSAMPLE_WEB=4  # Downsample for web display
OVERLAY_DOWNSAMPLE_HIGH=2  # Downsample for high quality
```

## New API Endpoints

### 1. Status Endpoint

```http
GET /api/radar/status
```

**Response:**
```json
{
  "scheduler": {
    "running": true,
    "update_in_progress": false,
    "update_interval": 300,
    "next_run": "2025-11-07T20:05:00",
    "last_check": "2025-11-07T20:00:00Z",
    "tracked_timestamps": 10
  },
  "latest_data": "20251107-200036",
  "cache_dir": "/path/to/cache",
  "update_interval": 300
}
```

### 2. Overlay Latest (Leaflet-Ready)

```http
GET /api/radar/overlay/latest
```

**Response:**
```json
{
  "timestamp": "2025-11-07T20:00:36Z",
  "image_url": "/api/radar/overlay/image/20251107-200036",
  "bounds": [[20.005, -129.995], [54.995, -60.005]],
  "resolution": "1km",
  "updated_at": "2025-11-07T20:05:00Z"
}
```

### 3. Overlay Image

```http
GET /api/radar/overlay/image/{timestamp}?quality=web
```

**Query Parameters:**
- `quality`: `web` (default, 4x downsample) or `high` (2x downsample)

**Response:** PNG image with transparency, optimized for web overlay

## React + Leaflet Integration

### Installation

```bash
npm install react-leaflet leaflet
```

### Example Component

```jsx
import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, ImageOverlay } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

const API_BASE = 'http://localhost:8000';

function RadarMap() {
  const [overlayData, setOverlayData] = useState(null);

  useEffect(() => {
    // Fetch initial data
    fetchOverlay();
    
    // Poll for updates every 5 minutes
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
        attribution='&copy; OpenStreetMap contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      
      {overlayData && (
        <ImageOverlay
          url={`${API_BASE}${overlayData.image_url}?quality=web`}
          bounds={overlayData.bounds}
          opacity={0.7}
        />
      )}
    </MapContainer>
  );
}

export default RadarMap;
```

### Advanced: Auto-Refresh with Status Check

```jsx
import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, ImageOverlay } from 'react-leaflet';

const API_BASE = 'http://localhost:8000';

function RadarMapWithStatus() {
  const [overlayData, setOverlayData] = useState(null);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    fetchStatus();
    fetchOverlay();
    
    // Check status every minute
    const statusInterval = setInterval(fetchStatus, 60 * 1000);
    
    // Fetch new overlay when data is updated
    const overlayInterval = setInterval(fetchOverlay, 5 * 60 * 1000);
    
    return () => {
      clearInterval(statusInterval);
      clearInterval(overlayInterval);
    };
  }, []);

  const fetchStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/radar/status`);
      const data = await response.json();
      setStatus(data);
    } catch (error) {
      console.error('Failed to fetch status:', error);
    }
  };

  const fetchOverlay = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/radar/overlay/latest`);
      const data = await response.json();
      setOverlayData(data);
    } catch (error) {
      console.error('Failed to fetch overlay:', error);
    }
  };

  if (!overlayData) return <div>Loading radar data...</div>;

  return (
    <div>
      <div style={{ padding: '10px', background: '#f0f0f0' }}>
        <strong>Status:</strong> {status?.scheduler.running ? '🟢 Running' : '🔴 Stopped'}
        {' | '}
        <strong>Latest Data:</strong> {status?.latest_data || 'N/A'}
        {' | '}
        <strong>Next Update:</strong> {
          status?.scheduler.next_run 
            ? new Date(status.scheduler.next_run).toLocaleTimeString() 
            : 'N/A'
        }
      </div>
      
      <MapContainer
        center={[37.5, -95]}
        zoom={5}
        style={{ height: '600px', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        
        <ImageOverlay
          url={`${API_BASE}${overlayData.image_url}?quality=web`}
          bounds={overlayData.bounds}
          opacity={0.7}
        />
      </MapContainer>
    </div>
  );
}

export default RadarMapWithStatus;
```

## Performance Characteristics

### Image Sizes

- **Web Quality** (4x downsample): ~1750x875 pixels, ~200-500 KB
- **High Quality** (2x downsample): ~3500x1750 pixels, ~800 KB - 2 MB
- Original data: ~7000x3500 pixels (not recommended for web)

### Caching

- Generated overlay images are cached on disk
- HTTP Cache-Control headers set to 5 minutes
- Reduces server load for repeated requests

### Update Frequency

- Default: Every 5 minutes
- MRMS updates typically every 2-5 minutes
- Duplicate detection prevents unnecessary downloads

## Troubleshooting

### No Data Available

If you see "No radar data available yet":
1. Check scheduler status: `GET /api/radar/status`
2. Wait 1-2 minutes for initial download
3. Manually trigger update: `POST /api/radar/update`

### Scheduler Not Running

Check logs for errors:
```bash
# View logs when running with uvicorn
uvicorn src.api:app --reload
```

### Testing Endpoints

```bash
# Check status
curl http://localhost:8000/api/radar/status

# Get latest overlay metadata
curl http://localhost:8000/api/radar/overlay/latest

# Download overlay image
curl http://localhost:8000/api/radar/overlay/image/20251107-200036?quality=web -o radar.png

# Manually trigger update
curl -X POST http://localhost:8000/api/radar/update
```

## Architecture Changes

### Before
- On-demand downloads on each API request
- No duplicate prevention
- Background tasks per request
- No scheduled updates

### After
- Independent scheduler with APScheduler
- Duplicate detection with timestamp tracking
- Cached data served from disk
- Scheduled updates every 5 minutes
- Optimized images for web visualization

