"""RALA (Reflectivity at Lowest Altitude) generation."""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple

import numpy as np
import gc
from PIL import Image
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for server
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from .processor import GRIB2Processor
from .utils import dbz_to_color
from .config import settings

logger = logging.getLogger(__name__)


class RALAGenerator:
    """Generate RALA product from MRMS data."""

    def __init__(self):
        """Initialize RALA generator."""
        self.processor = GRIB2Processor()

    def _create_radar_colormap(self) -> Tuple[mcolors.Colormap, mcolors.Normalize]:
        """
        Create standard NWS-style radar reflectivity colormap.
        
        Returns:
            Tuple of (colormap, normalizer) for reflectivity visualization
        """
        # Standard radar reflectivity color scale (NWS-style)
        # dBZ thresholds and corresponding RGB colors
        radar_colors = [
            (-30, (0, 236, 236)),      # Cyan - Very light
            (-20, (1, 160, 246)),      # Light blue
            (-10, (0, 0, 246)),        # Blue - Light rain
            (0, (0, 255, 0)),          # Green - Light rain
            (10, (0, 200, 0)),         # Dark green
            (20, (0, 144, 0)),         # Darker green - Moderate rain
            (30, (255, 255, 0)),       # Yellow - Heavy rain
            (35, (231, 192, 0)),       # Gold
            (40, (255, 144, 0)),       # Orange - Very heavy rain
            (45, (255, 0, 0)),         # Red - Intense rain
            (50, (214, 0, 0)),         # Dark red - Very intense
            (55, (192, 0, 0)),         # Darker red
            (60, (255, 0, 255)),       # Magenta - Extreme
            (65, (153, 85, 201)),      # Purple - Hail likely
            (70, (255, 255, 255)),     # White - Large hail
            (75, (255, 255, 255)),     # White - Extend to max
        ]
        
        # Extract values and colors
        dbz_values = [item[0] for item in radar_colors]
        rgb_colors = [tuple(c/255 for c in item[1]) for item in radar_colors]
        
        # Define range
        dbz_min, dbz_max = -30, 75
        norm = mcolors.Normalize(vmin=dbz_min, vmax=dbz_max)
        
        # Normalize the dBZ values to 0-1 range for colormap
        normalized_positions = [(v - dbz_min) / (dbz_max - dbz_min) for v in dbz_values]
        
        # Ensure exactly 0.0 and 1.0 at the boundaries
        normalized_positions[0] = 0.0
        normalized_positions[-1] = 1.0
        
        # Create the colormap
        cmap = mcolors.LinearSegmentedColormap.from_list(
            'radar', 
            list(zip(normalized_positions, rgb_colors))
        )
        
        # Set NaN/missing data to transparent
        cmap.set_bad(color='none', alpha=0)
        
        return cmap, norm

    def generate_rala_single(
        self,
        file_path: Path,
        min_dbz: float = -30.0,
        max_dbz: float = 80.0
    ) -> Dict[str, Any]:
        """
        Generate RALA from a single elevation angle file.
        
        For now, since we're only using 0.50° elevation, RALA is simply
        the QC'd reflectivity at that elevation.
        
        In the future, this could combine multiple elevation angles.
        
        Args:
            file_path: Path to GRIB2 file
            min_dbz: Minimum valid reflectivity
            max_dbz: Maximum valid reflectivity
            
        Returns:
            Dictionary with RALA data and metadata
        """
        logger.info(f"Generating RALA from {file_path.name}")
        
        # Process GRIB2 file
        processed = self.processor.process_file(file_path)
        
        # Apply QC
        rala_data = self.processor.apply_quality_control(
            processed["reflectivity"],
            min_value=min_dbz,
            max_value=max_dbz
        )
        
        # Extract coordinates from dataset
        dataset = processed["dataset"]
        latitude = None
        longitude = None
        
        # Try to find latitude/longitude coordinates
        lat_names = ['latitude', 'lat', 'y']
        lon_names = ['longitude', 'lon', 'x']
        
        for name in lat_names:
            if name in dataset.coords:
                latitude = dataset.coords[name].values
                break
        
        for name in lon_names:
            if name in dataset.coords:
                longitude = dataset.coords[name].values
                break
        
        # Create 2D meshgrid if coordinates are 1D
        if latitude is not None and longitude is not None:
            if latitude.ndim == 1 and longitude.ndim == 1:
                longitude, latitude = np.meshgrid(longitude, latitude)
            
            # Convert longitude from 0-360 to -180-180 if needed (for Leaflet compatibility)
            longitude = np.where(longitude > 180, longitude - 360, longitude)
        
        return {
            "rala": rala_data,
            "metadata": processed["metadata"],
            "file_path": str(file_path),
            "dataset": dataset,
            "latitude": latitude,
            "longitude": longitude,
        }

    def generate_rala(
        self,
        file_paths: Union[Dict[float, Path], List[Path]],
        min_dbz: float = -30.0,
        max_dbz: float = 80.0,
        elevation_angles: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Generate RALA from multiple elevation angles (or single file).
        
        This is now the primary method for RALA generation. It automatically
        handles both single-file and multi-elevation processing.
        
        Algorithm:
        1. Load all elevation angles
        2. For each grid point, select lowest altitude with valid data
        3. Lowest altitude = lowest elevation angle (since height increases with angle)
        
        Args:
            file_paths: Dict mapping elevation to Path, or List of Paths
            min_dbz: Minimum valid reflectivity
            max_dbz: Maximum valid reflectivity
            elevation_angles: List of elevation angles (if known, for List input)
            
        Returns:
            Dictionary with RALA data and metadata
        """
        # Handle both dict and list inputs
        if isinstance(file_paths, dict):
            # Sort by elevation angle (lowest first)
            sorted_items = sorted(file_paths.items(), key=lambda x: x[0])
            sorted_paths = [path for _, path in sorted_items]
            elevations = [elev for elev, _ in sorted_items]
            logger.info(f"Generating RALA from {len(sorted_paths)} elevation angles: {elevations}")
        else:
            sorted_paths = file_paths
            elevations = elevation_angles or []
            logger.info(f"Generating RALA from {len(sorted_paths)} elevation angles")
        
        if not sorted_paths:
            raise ValueError("No files provided")
        
        # Handle single file case
        if len(sorted_paths) == 1:
            logger.info("Single elevation angle, using simplified processing")
            return self.generate_rala_single(
                sorted_paths[0],
                min_dbz=min_dbz,
                max_dbz=max_dbz
            )
        
        # Load all files
        # Process files sequentially to minimize peak memory usage
        metadata = None
        dataset = None
        latitude = None
        longitude = None
        rala: Optional[np.ndarray] = None
        
        for file_path in sorted_paths:
            processed = self.processor.process_file(file_path)
            rala_data = self.processor.apply_quality_control(
                processed["reflectivity"],
                min_value=min_dbz,
                max_value=max_dbz
            )
            
            if metadata is None:
                metadata = processed["metadata"]
                dataset = processed["dataset"]
                
                # Extract coordinates from first dataset
                lat_names = ['latitude', 'lat', 'y']
                lon_names = ['longitude', 'lon', 'x']
                
                for name in lat_names:
                    if name in dataset.coords:
                        latitude = dataset.coords[name].values
                        break
                
                for name in lon_names:
                    if name in dataset.coords:
                        longitude = dataset.coords[name].values
                        break
                
                # Create 2D meshgrid if coordinates are 1D
                if latitude is not None and longitude is not None:
                    if latitude.ndim == 1 and longitude.ndim == 1:
                        longitude, latitude = np.meshgrid(longitude, latitude)
                    
                    # Convert longitude from 0-360 to -180-180 if needed (for Leaflet compatibility)
                    longitude = np.where(longitude > 180, longitude - 360, longitude)
            
            # Initialize output with the first (lowest) elevation
            if rala is None:
                # Make an explicit float32 array for memory efficiency
                rala = np.array(rala_data, dtype=np.float32, copy=True)
            else:
                # Fill only where we don't yet have data and current level is valid
                # Avoid allocating large temporaries by using boolean masks
                missing_mask = np.isnan(rala)
                if np.any(missing_mask):
                    valid_mask = ~np.isnan(rala_data)
                    fill_mask = missing_mask & valid_mask
                    if np.any(fill_mask):
                        rala[fill_mask] = rala_data[fill_mask]
            
            # Proactively free memory for the current level before next iteration
            del rala_data, processed
            gc.collect()
        
        logger.info(f"RALA generation complete: "
                   f"{np.sum(~np.isnan(rala))} valid points")
        
        return {
            "rala": rala,
            "metadata": metadata,
            "n_elevations": len(sorted_paths),
            "elevation_angles": elevations,
            "file_paths": [str(p) for p in sorted_paths],
            "dataset": dataset,
            "latitude": latitude,
            "longitude": longitude,
        }

    def generate_rala_multi(
        self,
        file_paths: List[Path],
        elevation_angles: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Generate RALA from multiple elevation angles.
        
        Deprecated: Use generate_rala() instead, which handles both single
        and multi-elevation cases.
        
        Args:
            file_paths: List of GRIB2 files at different elevations
            elevation_angles: List of elevation angles (if known)
            
        Returns:
            Dictionary with RALA data and metadata
        """
        logger.warning("generate_rala_multi() is deprecated, use generate_rala() instead")
        return self.generate_rala(file_paths, elevation_angles=elevation_angles)

    def rala_to_image(
        self,
        rala_data: np.ndarray,
        latitude: Optional[np.ndarray] = None,
        longitude: Optional[np.ndarray] = None,
        output_path: Optional[Path] = None,
        downsample: int = 1,
        title: Optional[str] = None,
        dpi: int = 150,
        figsize: Tuple[float, float] = (16, 12)
    ) -> Path:
        """
        Convert RALA data to a PNG image with geographic context.
        
        Creates a high-quality geographic visualization with state boundaries,
        coastlines, borders, and gridlines similar to professional weather radar
        displays.
        
        Args:
            rala_data: RALA reflectivity array
            latitude: 2D latitude array (must match rala_data shape)
            longitude: 2D longitude array (must match rala_data shape)
            output_path: Optional path to save image
            downsample: Downsampling factor (1 = no downsampling)
            title: Optional title for the image
            dpi: Resolution in dots per inch (default: 150)
            figsize: Figure size in inches (width, height)
            
        Returns:
            Path to saved image
        """
        logger.info(f"Converting RALA to geographic image (downsample={downsample}, dpi={dpi})")
        
        # Downsample if requested
        if downsample > 1:
            rala_data = rala_data[::downsample, ::downsample]
            if latitude is not None:
                latitude = latitude[::downsample, ::downsample]
            if longitude is not None:
                longitude = longitude[::downsample, ::downsample]
        
        # Get radar colormap
        cmap, norm = self._create_radar_colormap()
        
        # Create figure with geographic projection
        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = plt.axes(projection=ccrs.PlateCarree())
        
        # Add geographic features
        ax.add_feature(cfeature.STATES.with_scale('50m'), linewidth=0.5, edgecolor='black')
        ax.add_feature(cfeature.COASTLINE.with_scale('50m'), linewidth=1.0)
        ax.add_feature(cfeature.BORDERS.with_scale('50m'), linewidth=0.5, linestyle=':')
        
        # Plot reflectivity data if coordinates are available
        if latitude is not None and longitude is not None:
            im = ax.pcolormesh(
                longitude, latitude, rala_data,
                cmap=cmap, norm=norm,
                transform=ccrs.PlateCarree(),
                shading='auto', alpha=0.8
            )
            
            # Set map extent based on data bounds with padding
            padding = 2  # degrees
            ax.set_extent([
                longitude.min() - padding,
                longitude.max() + padding,
                latitude.min() - padding,
                latitude.max() + padding
            ], crs=ccrs.PlateCarree())
        else:
            # Fallback: plot without coordinates (less useful)
            logger.warning("No coordinates provided, creating non-geographic visualization")
            im = ax.imshow(
                rala_data,
                cmap=cmap, norm=norm,
                origin='lower', alpha=0.8
            )
        
        # Add gridlines with labels
        gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', 
                         alpha=0.5, linestyle='--')
        gl.top_labels = False
        gl.right_labels = False
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax, orientation='vertical', 
                           pad=0.02, shrink=0.7)
        cbar.set_label('Reflectivity (dBZ)', fontsize=12, fontweight='bold')
        
        # Add title
        if title:
            ax.set_title(title, fontsize=14, fontweight='bold', pad=10)
        else:
            ax.set_title('MRMS Radar Reflectivity', fontsize=14, 
                        fontweight='bold', pad=10)
        
        # Add data info box
        valid_mask = ~np.isnan(rala_data)
        valid_count = valid_mask.sum()
        if valid_count > 0:
            valid_data = rala_data[valid_mask]
            info_text = (f"Valid points: {valid_count:,}\n"
                        f"Range: {valid_data.min():.1f} to {valid_data.max():.1f} dBZ")
            ax.text(0.02, 0.98, info_text, transform=ax.transAxes,
                   verticalalignment='top', horizontalalignment='left',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8),
                   fontsize=10, family='monospace')
        
        # Save figure
        if output_path is None:
            output_path = settings.cache_dir / "radar_temp.png"
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        plt.close(fig)
        
        logger.info(f"Saved geographic radar image to {output_path}")
        
        return output_path

    def rala_to_overlay(
        self,
        rala_data: np.ndarray,
        latitude: Optional[np.ndarray] = None,
        longitude: Optional[np.ndarray] = None,
        output_path: Optional[Path] = None,
        downsample: int = 1
    ) -> Tuple[Path, Dict[str, float]]:
        """
        Create a transparent overlay image suitable for web map libraries like Leaflet.
        
        This method generates ONLY the radar data as a transparent PNG without any
        map features (no states, coastlines, gridlines, etc.). Perfect for overlaying
        on interactive web maps.
        
        Args:
            rala_data: RALA reflectivity array
            latitude: 2D latitude array (must match rala_data shape)
            longitude: 2D longitude array (must match rala_data shape)
            output_path: Optional path to save image
            downsample: Downsampling factor (1 = no downsampling)
            
        Returns:
            Tuple of (image_path, bounds_dict) where bounds_dict contains:
            - north, south, east, west coordinates for map overlay positioning
        """
        logger.info(f"Converting RALA to transparent overlay (downsample={downsample})")
        
        # Downsample if requested
        if downsample > 1:
            rala_data = rala_data[::downsample, ::downsample]
            if latitude is not None:
                latitude = latitude[::downsample, ::downsample]
            if longitude is not None:
                longitude = longitude[::downsample, ::downsample]
        
        # Convert longitude from 0-360 to -180-180 if needed (for Leaflet compatibility)
        if longitude is not None:
            longitude = np.where(longitude > 180, longitude - 360, longitude)
        
        # Get radar colormap
        cmap, norm = self._create_radar_colormap()
        
        # Calculate bounds for Leaflet
        if latitude is not None and longitude is not None:
            bounds = {
                'north': float(latitude.max()),
                'south': float(latitude.min()),
                'east': float(longitude.max()),
                'west': float(longitude.min())
            }
        else:
            # Fallback to CONUS if no coordinates provided
            bounds = {
                'north': 54.995,
                'south': 20.005,
                'east': -60.005,
                'west': -129.995
            }
        
        # Create figure with exact dimensions (no padding, no axes)
        height, width = rala_data.shape
        dpi = 100
        figsize = (width / dpi, height / dpi)
        
        fig = plt.figure(figsize=figsize, dpi=dpi, frameon=False)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis('off')
        
        # Plot ONLY the radar data (origin='upper' for correct lat orientation)
        ax.imshow(rala_data, cmap=cmap, norm=norm, 
                 origin='upper', interpolation='nearest', aspect='auto')
        
        # Save figure
        if output_path is None:
            output_path = settings.cache_dir / "radar_overlay_temp.png"
        
        # Save without bbox_inches='tight' to preserve exact dimensions
        # This is critical for geographic overlay alignment
        plt.savefig(output_path, dpi=dpi, transparent=True, 
                   bbox_inches=None, pad_inches=0)
        plt.close(fig)
        
        logger.info(f"Saved transparent overlay to {output_path}")
        logger.info(f"Overlay bounds: {bounds}")
        
        return output_path, bounds

    def rala_to_geojson(
        self,
        rala_data: np.ndarray,
        metadata: Dict[str, Any],
        downsample: int = 4,
        min_dbz: float = 5.0
    ) -> Dict[str, Any]:
        """
        Convert RALA data to GeoJSON format (for vector rendering).
        
        Warning: This can be very large for full resolution data.
        
        Args:
            rala_data: RALA reflectivity array
            metadata: Metadata with bounds information
            downsample: Downsampling factor
            min_dbz: Minimum dBZ to include (filter weak echoes)
            
        Returns:
            GeoJSON FeatureCollection dictionary
        """
        logger.info(f"Converting RALA to GeoJSON (downsample={downsample})")
        
        # Downsample
        if downsample > 1:
            rala_data = rala_data[::downsample, ::downsample]
        
        height, width = rala_data.shape
        
        # Get bounds
        bounds = metadata.get("bounds", {})
        north = bounds.get("north", 54.995)
        south = bounds.get("south", 20.005)
        east = bounds.get("east", -60.005)
        west = bounds.get("west", -129.995)
        
        # Calculate lat/lon for each pixel
        lats = np.linspace(north, south, height)
        lons = np.linspace(west, east, width)
        
        # Create GeoJSON features
        features = []
        for i in range(height):
            for j in range(width):
                dbz = rala_data[i, j]
                if not np.isnan(dbz) and dbz >= min_dbz:
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [float(lons[j]), float(lats[i])]
                        },
                        "properties": {
                            "reflectivity": float(dbz),
                            "color": "#{:02x}{:02x}{:02x}".format(*dbz_to_color(dbz)[:3])
                        }
                    })
        
        logger.info(f"Created GeoJSON with {len(features)} features")
        
        return {
            "type": "FeatureCollection",
            "features": features
        }


# Convenience functions
def generate_rala_from_path(file_path: Union[Path, Dict[float, Path], List[Path]]) -> Dict[str, Any]:
    """
    Generate RALA from GRIB2 file(s).
    
    Convenience function that handles single files, lists, or dicts of files.
    
    Args:
        file_path: Single Path, Dict mapping elevation to Path, or List of Paths
        
    Returns:
        RALA data dictionary
    """
    generator = RALAGenerator()
    
    if isinstance(file_path, (dict, list)):
        return generator.generate_rala(file_path)
    else:
        return generator.generate_rala_single(file_path)

