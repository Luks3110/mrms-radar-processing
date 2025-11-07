"""FastAPI application for serving radar data."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .scraper import MRMSScraper
from .rala import RALAGenerator
from .utils import (
    parse_mrms_filename, 
    format_timestamp,
    get_latest_cached_timestamp,
    get_latest_cached_files
)
from .scheduler import start_scheduler, shutdown_scheduler, get_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="MRMS Radar API",
    description="API for processing and serving MRMS weather radar data",
    version="0.1.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
scraper = MRMSScraper()
rala_generator = RALAGenerator()


# Lifecycle events
@app.on_event("startup")
async def startup_event():
    """Initialize services on app startup."""
    logger.info("Starting up MRMS Radar API...")
    await start_scheduler()
    logger.info("Startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on app shutdown."""
    logger.info("Shutting down MRMS Radar API...")
    await shutdown_scheduler()
    logger.info("Shutdown complete")


# Response models
class RadarMetadata(BaseModel):
    """Metadata for radar data."""
    timestamp: datetime
    bounds: dict
    data_url: str
    image_url: Optional[str] = None


class FileInfo(BaseModel):
    """Information about a radar file."""
    filename: str
    timestamp: datetime
    size: str
    processed: bool


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "MRMS Radar API",
        "version": "0.1.0",
        "description": "Automated radar data updates with Leaflet-optimized visualization",
        "endpoints": {
            "status": "/api/radar/status",
            "overlay_latest": "/api/radar/overlay/latest",
            "overlay_by_timestamp": "/api/radar/overlay/{timestamp}",
            "overlay_image": "/api/radar/overlay/{timestamp}/image",
            "radar_latest": "/api/radar/latest",
            "radar_image": "/api/radar/image/{timestamp}",
            "radar_data": "/api/radar/data/{timestamp}",
            "file_list": "/api/radar/files",
            "health": "/health",
        },
        "features": {
            "auto_update_interval": f"{settings.update_interval}s",
            "duplicate_detection": True,
            "leaflet_ready": True,
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "cache_dir": str(settings.cache_dir),
        "cached_files": len(list(settings.cache_dir.glob("*.grib2")))
    }


@app.get("/api/radar/latest", response_model=RadarMetadata)
async def get_latest_radar(use_multi_elevation: bool = True):
    """
    Get metadata for the latest available radar data from cache.
    
    This endpoint returns information about the latest cached radar file.
    Data is automatically updated in the background by the scheduler.
    
    Args:
        use_multi_elevation: Use multi-elevation RALA composite (default: True)
    """
    try:
        if use_multi_elevation:
            # Get latest cached files for all elevations
            elevation_files = get_latest_cached_files(settings.cache_dir, settings.elevation_angles)
            
            if not elevation_files:
                raise HTTPException(
                    status_code=503, 
                    detail="No radar data available yet. The background updater will fetch data shortly."
                )
            
            # Get timestamp from any file (they should all match)
            first_file = next(iter(elevation_files.values()))
            timestamp = parse_mrms_filename(first_file.name)
            
            if timestamp is None:
                raise HTTPException(status_code=500, detail="Failed to parse timestamp")
            
            # Avoid generating full RALA here to reduce memory pressure.
            # Use lightweight default bounds; detailed bounds are computed during image generation.
            metadata = {"bounds": {"south": 20.005, "west": -129.995, "north": 54.995, "east": -60.005}}
            
        else:
            # Fallback to single elevation
            logger.info("Using single elevation (0.50 km)...")
            latest_timestamp = get_latest_cached_timestamp(settings.cache_dir, elevation=0.50)
            
            if latest_timestamp is None:
                raise HTTPException(
                    status_code=503, 
                    detail="No radar data available yet. The background updater will fetch data shortly."
                )
            
            # Find the cached file
            cache_path = scraper.get_cache_path(0.50)
            pattern = f"*{latest_timestamp}.grib2"
            matching_files = list(cache_path.glob(pattern))
            
            if not matching_files:
                raise HTTPException(status_code=404, detail="Cached file not found")
            
            latest_file = matching_files[0]
            timestamp = parse_mrms_filename(latest_file.name)
            
            if timestamp is None:
                raise HTTPException(status_code=500, detail="Failed to parse timestamp")
            
            # Avoid generating full RALA here to reduce memory pressure.
            metadata = {"bounds": {"south": 20.005, "west": -129.995, "north": 54.995, "east": -60.005}}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process radar data: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to process radar data: {str(e)}")
    
    timestamp_str = format_timestamp(timestamp)
    
    return RadarMetadata(
        timestamp=timestamp,
        bounds=metadata.get("bounds", {}),
        data_url=f"/api/radar/data/{timestamp_str}",
        image_url=f"/api/radar/image/{timestamp_str}"
    )


@app.get("/api/radar/status")
async def get_radar_status():
    """
    Get status of the radar data system.
    
    Returns information about the scheduler and last update.
    """
    # Get live scheduler status
    scheduler = get_scheduler()
    status = scheduler.get_status()
    
    # Add latest cached timestamp
    latest_timestamp = get_latest_cached_timestamp(settings.cache_dir, elevation=0.50)
    
    return {
        "scheduler": "running" if status.get("running") else "stopped",
        "scheduler_details": status,
        "latest_data": latest_timestamp,
        "cache_dir": str(settings.cache_dir),
        "update_interval": settings.update_interval,
    }


class OverlayMetadata(BaseModel):
    """Metadata for radar overlay visualization."""
    timestamp: datetime
    image_url: str
    bounds: List[List[float]]  # [[south, west], [north, east]] for Leaflet
    resolution: str
    updated_at: str


@app.get("/api/radar/overlay/latest", response_model=OverlayMetadata)
async def get_latest_overlay():
    """
    Get latest radar data optimized for Leaflet overlay.
    
    Returns JSON with image URL and georeferencing metadata ready for
    use with Leaflet's ImageOverlay component.
    """
    try:
        # Get latest cached files
        elevation_files = get_latest_cached_files(settings.cache_dir, settings.elevation_angles)
        
        if not elevation_files:
            raise HTTPException(
                status_code=503,
                detail="No radar data available yet. The background updater will fetch data shortly."
            )
        
        # Get timestamp from first file
        first_file = next(iter(elevation_files.values()))
        timestamp = parse_mrms_filename(first_file.name)
        
        if timestamp is None:
            raise HTTPException(status_code=500, detail="Failed to parse timestamp")
        
        timestamp_str = format_timestamp(timestamp)
        
        # Use lightweight static CONUS bounds here to avoid heavy array loads.
        # The exact bounds for the image are derived during image generation.
        bounds = [[20.005, -129.995], [54.995, -60.005]]
        
        return OverlayMetadata(
            timestamp=timestamp,
            image_url=f"/api/radar/overlay/image/{timestamp_str}",
            bounds=bounds,
            resolution="1km",
            updated_at=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get overlay metadata: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to get overlay data: {str(e)}")


@app.get("/api/radar/overlay/image/{timestamp}")
async def get_overlay_image(timestamp: str, quality: str = "web"):
    """
    Get optimized radar overlay image for Leaflet.
    
    Returns a PNG with transparency, downsampled for efficient web rendering.
    
    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMMSS
        quality: Quality level - "web" (4x downsample) or "high" (2x downsample)
    """
    # Determine downsample factor
    if quality == "high":
        downsample = settings.overlay_downsample_high
    else:
        downsample = settings.overlay_downsample_web
    
    # Check for cached image first
    cache_filename = f"overlay_{timestamp}_q{quality}.png"
    cached_image = settings.cache_dir / cache_filename
    
    if cached_image.exists():
        logger.info(f"Serving cached overlay image: {cache_filename}")
        return FileResponse(
            cached_image,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"}
        )
    
    # Generate image if not cached
    try:
        # Get all elevation files for this timestamp
        elevation_files = {}
        for elevation in settings.elevation_angles:
            cache_path = scraper.get_cache_path(elevation)
            pattern = f"*{timestamp}.grib2"
            matching_files = list(cache_path.glob(pattern))
            if matching_files:
                elevation_files[elevation] = matching_files[0]
        
        if not elevation_files:
            raise HTTPException(status_code=404, detail=f"No radar data found for {timestamp}")
        
        # Generate RALA composite
        rala_result = rala_generator.generate_rala(elevation_files)
        
        # Convert to transparent overlay with downsampling
        logger.info(f"Generating overlay image with downsample={downsample}")
        rala_generator.rala_to_overlay(
            rala_result["rala"],
            latitude=rala_result.get("latitude"),
            longitude=rala_result.get("longitude"),
            output_path=cached_image,
            downsample=downsample
        )
        
        return FileResponse(
            cached_image,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate overlay image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate overlay image: {str(e)}")


@app.get("/api/radar/image/{timestamp}")
async def get_radar_image(timestamp: str, downsample: int = 2):
    """
    Get radar data as a PNG image.
    
    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMMSS
        downsample: Downsampling factor (default: 2)
    """
    # Find matching file (search recursively for elevation subdirs)
    pattern = f"**/*{timestamp}.grib2"
    matching_files = list(settings.cache_dir.glob(pattern))
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"No radar data found for {timestamp}")
    
    file_path = matching_files[0]
    
    # Generate RALA
    try:
        rala_result = rala_generator.generate_rala_single(file_path)
        
        # Parse timestamp for title
        parsed_time = parse_mrms_filename(file_path.name)
        title = f"MRMS Reflectivity at 0.50° Elevation\n{parsed_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        
        # Convert to image with geographic context
        output_path = settings.cache_dir / f"rala_{timestamp}.png"
        image_path = rala_generator.rala_to_image(
            rala_result["rala"],
            latitude=rala_result.get("latitude"),
            longitude=rala_result.get("longitude"),
            output_path=output_path,
            downsample=downsample,
            title=title
        )
        
        return FileResponse(
            image_path,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"}
        )
        
    except Exception as e:
        logger.error(f"Failed to generate image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate image: {str(e)}")


@app.get("/api/radar/overlay/{timestamp}")
async def get_radar_overlay(timestamp: str, downsample: int = 2):
    """
    Get radar data as a transparent PNG overlay for web maps (Leaflet, MapBox, etc).
    
    This endpoint returns a transparent radar overlay WITHOUT map features,
    perfect for use with React Leaflet's ImageOverlay component.
    
    Returns JSON with:
    - image_url: URL to the transparent PNG
    - bounds: Geographic bounds [[south, west], [north, east]]
    - timestamp: Data timestamp
    
    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMMSS
        downsample: Downsampling factor (default: 2)
    """
    # Find matching file (search recursively for elevation subdirs)
    pattern = f"**/*{timestamp}.grib2"
    matching_files = list(settings.cache_dir.glob(pattern))
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"No radar data found for {timestamp}")
    
    file_path = matching_files[0]
    
    # Generate RALA and overlay
    try:
        rala_result = rala_generator.generate_rala_single(file_path)
        
        # Convert to transparent overlay
        overlay_path = settings.cache_dir / f"overlay_{timestamp}.png"
        image_path, bounds = rala_generator.rala_to_overlay(
            rala_result["rala"],
            latitude=rala_result.get("latitude"),
            longitude=rala_result.get("longitude"),
            output_path=overlay_path,
            downsample=downsample
        )
        
        # Parse timestamp
        parsed_time = parse_mrms_filename(file_path.name)
        
        # Format bounds for Leaflet: [[south, west], [north, east]]
        leaflet_bounds = [
            [bounds['south'], bounds['west']],
            [bounds['north'], bounds['east']]
        ]
        
        # Return metadata with image URL
        return JSONResponse({
            "timestamp": parsed_time.isoformat(),
            "image_url": f"/api/radar/overlay/{timestamp}/image",
            "bounds": leaflet_bounds,
            "resolution": f"{rala_result['rala'].shape[0]}x{rala_result['rala'].shape[1]}",
            "downsample": downsample,
            "cache_control": "public, max-age=300"
        })
        
    except Exception as e:
        logger.error(f"Failed to generate overlay: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate overlay: {str(e)}")


@app.get("/api/radar/overlay/{timestamp}/image")
async def get_radar_overlay_image(timestamp: str, downsample: int = 2):
    """
    Get the actual transparent PNG overlay image.
    
    This is typically called automatically by the frontend after getting
    metadata from /api/radar/overlay/{timestamp}.
    
    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMMSS
        downsample: Downsampling factor (default: 2)
    """
    # Check if overlay already exists in cache
    overlay_path = settings.cache_dir / f"overlay_{timestamp}.png"
    
    if not overlay_path.exists():
        # Generate it if it doesn't exist
        pattern = f"**/*{timestamp}.grib2"
        matching_files = list(settings.cache_dir.glob(pattern))
        
        if not matching_files:
            raise HTTPException(status_code=404, detail=f"No radar data found for {timestamp}")
        
        file_path = matching_files[0]
        
        try:
            rala_result = rala_generator.generate_rala_single(file_path)
            image_path, _ = rala_generator.rala_to_overlay(
                rala_result["rala"],
                latitude=rala_result.get("latitude"),
                longitude=rala_result.get("longitude"),
                output_path=overlay_path,
                downsample=downsample
            )
        except Exception as e:
            logger.error(f"Failed to generate overlay image: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to generate overlay image: {str(e)}")
    
    return FileResponse(
        overlay_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"}
    )


@app.get("/api/radar/data/{timestamp}")
async def get_radar_data(timestamp: str):
    """
    Get raw radar data as JSON.
    
    Warning: This can be very large. Consider using the image endpoint instead.
    
    Args:
        timestamp: Timestamp in format YYYYMMDD-HHMMSS
    """
    # Find matching file (search recursively for elevation subdirs)
    pattern = f"**/*{timestamp}.grib2"
    matching_files = list(settings.cache_dir.glob(pattern))
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"No radar data found for {timestamp}")
    
    file_path = matching_files[0]
    
    try:
        rala_result = rala_generator.generate_rala_single(file_path)
        
        # Convert numpy array to list for JSON serialization (guarded)
        rala_data = rala_result["rala"]
        shape = list(rala_data.shape)
        total_elements = int(rala_data.size)
        payload = {
            "timestamp": timestamp,
            "metadata": rala_result["metadata"],
            "shape": shape,
        }
        # Only include raw data when under a safe threshold to avoid OOM
        if total_elements <= 1_000_000:
            payload["data"] = rala_data.tolist()
        else:
            payload["note"] = "Data omitted due to size; request image/overlay endpoints instead."
        
        return JSONResponse(payload)
        
    except Exception as e:
        logger.error(f"Failed to get radar data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get data: {str(e)}")


@app.get("/api/radar/files", response_model=List[FileInfo])
async def list_radar_files(limit: int = 24):
    """
    List available radar files.
    
    Args:
        limit: Maximum number of files to return
    """
    cached_files = scraper.get_cached_files()[:limit]
    
    file_list = []
    for file_path in cached_files:
        timestamp = parse_mrms_filename(file_path.name)
        file_list.append(FileInfo(
            filename=file_path.name,
            timestamp=timestamp,
            size=f"{file_path.stat().st_size / 1024:.0f}K",
            processed=True
        ))
    
    return file_list


@app.post("/api/radar/update")
async def trigger_update():
    """
    Manually trigger a radar data update.
    
    The scheduler will handle the actual download to avoid duplicates.
    """
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("📡 /api/radar/update endpoint called - Manual update triggered")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    scheduler = get_scheduler()
    scheduler_status = scheduler.get_status()
    
    logger.info(f"Scheduler status: running={scheduler_status['running']}, "
                f"update_in_progress={scheduler_status['update_in_progress']}")
    
    if scheduler_status['update_in_progress']:
        logger.warning("⚠️  Update already in progress, creating task anyway (will be skipped by scheduler)")
    
    # Trigger an immediate update
    import asyncio
    task = asyncio.create_task(scheduler.update_radar_data())
    logger.info(f"✅ Background task created: {task}")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    return {
        "status": "Update triggered",
        "message": "Background update started. Check /api/radar/status for progress."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )

