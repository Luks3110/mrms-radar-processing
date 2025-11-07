"""GRIB2 file processor using xarray and cfgrib."""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import numpy as np
import xarray as xr
import cfgrib
from metpy.units import units

from .config import settings

logger = logging.getLogger(__name__)


class GRIB2Processor:
    """Process GRIB2 radar files using MetPy."""

    def __init__(self):
        """Initialize GRIB2 processor."""
        pass

    def load_grib2(self, file_path: Path) -> xr.Dataset:
        """
        Load GRIB2 file using xarray and cfgrib.
        
        Args:
            file_path: Path to GRIB2 file
            
        Returns:
            xarray Dataset with radar data
        """
        logger.info(f"Loading GRIB2 file: {file_path}")
        
        if not file_path.exists():
            raise FileNotFoundError(f"GRIB2 file not found: {file_path}")
        
        try:
            # Read GRIB2 file with xarray + cfgrib engine
            ds = xr.open_dataset(str(file_path), engine='cfgrib')
            logger.info(f"Successfully loaded GRIB2 file with {len(ds.data_vars)} variables")
            return ds
            
        except Exception as e:
            logger.error(f"Failed to load GRIB2 file: {e}")
            # Try with error handling
            try:
                logger.info("Attempting to load with error tolerance...")
                ds = xr.open_dataset(str(file_path), engine='cfgrib', 
                                    backend_kwargs={'errors': 'ignore'})
                logger.info(f"Successfully loaded GRIB2 file with error tolerance")
                return ds
            except Exception as e2:
                logger.error(f"Failed to load GRIB2 file even with error tolerance: {e2}")
                raise

    def extract_reflectivity(self, dataset: xr.Dataset) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Extract reflectivity data and metadata from dataset.
        
        Args:
            dataset: xarray Dataset from GRIB2 file
            
        Returns:
            Tuple of (reflectivity_array, metadata_dict)
        """
        logger.info("Extracting reflectivity data")
        
        # Find reflectivity variable (may have different names)
        # Common names: MergedReflectivityQCComposite, Reflectivity, refc
        reflectivity_var = None
        for var_name in dataset.data_vars:
            var = dataset[var_name]
            if 'reflectivity' in var_name.lower() or 'refc' in var_name.lower():
                reflectivity_var = var
                logger.info(f"Found reflectivity variable: {var_name}")
                break
        
        if reflectivity_var is None:
            # If not found by name, take the first data variable
            var_name = list(dataset.data_vars)[0]
            reflectivity_var = dataset[var_name]
            logger.warning(f"Reflectivity variable not found by name, using: {var_name}")
        
        # Extract data array
        data = reflectivity_var.values
        # Ensure memory-efficient dtype
        if data.dtype != np.float32:
            # Cast to float32 to cut memory usage roughly in half
            data = data.astype(np.float32, copy=False)
        
        # Get coordinate information
        if 'latitude' in dataset.coords and 'longitude' in dataset.coords:
            lats = dataset['latitude'].values
            lons = dataset['longitude'].values
        elif 'y' in dataset.coords and 'x' in dataset.coords:
            # May need to derive lat/lon from projection coordinates
            logger.warning("Lat/lon not found directly, may need coordinate transformation")
            lats = dataset['y'].values
            lons = dataset['x'].values
        else:
            logger.error("Could not find coordinate information")
            lats = None
            lons = None
        
        # Build metadata
        metadata = {
            "shape": data.shape,
            "dtype": str(data.dtype),
            "units": str(reflectivity_var.attrs.get('units', 'dBZ')),
            "min_value": float(np.nanmin(data)),
            "max_value": float(np.nanmax(data)),
            "mean_value": float(np.nanmean(data)),
            "missing_value": reflectivity_var.attrs.get('missing_value', np.nan),
            "valid_range": reflectivity_var.attrs.get('valid_range', None),
        }
        
        if lats is not None and lons is not None:
            metadata["bounds"] = {
                "north": float(np.max(lats)),
                "south": float(np.min(lats)),
                "east": float(np.max(lons)),
                "west": float(np.min(lons)),
            }
            metadata["grid_shape"] = {
                "nlat": lats.shape[0] if lats.ndim == 1 else lats.shape[0],
                "nlon": lons.shape[0] if lons.ndim == 1 else lons.shape[1] if lons.ndim == 2 else lons.shape[0],
            }
        
        logger.info(f"Extracted reflectivity: shape={data.shape}, "
                   f"range=[{metadata['min_value']:.1f}, {metadata['max_value']:.1f}] dBZ")
        
        return data, metadata

    def process_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Process a GRIB2 file and extract all relevant information.
        
        Args:
            file_path: Path to GRIB2 file
            
        Returns:
            Dictionary with processed data and metadata
        """
        dataset = self.load_grib2(file_path)
        reflectivity, metadata = self.extract_reflectivity(dataset)
        
        return {
            "file_path": str(file_path),
            "reflectivity": reflectivity,
            "metadata": metadata,
            "dataset": dataset,  # Keep for further processing
        }

    def apply_quality_control(
        self,
        data: np.ndarray,
        min_value: float = -30.0,
        max_value: float = 80.0
    ) -> np.ndarray:
        """
        Apply quality control thresholds to reflectivity data.
        
        Args:
            data: Reflectivity array
            min_value: Minimum valid dBZ value
            max_value: Maximum valid dBZ value
            
        Returns:
            QC'd array with invalid values set to NaN
        """
        logger.info(f"Applying QC: valid range [{min_value}, {max_value}] dBZ")
        
        qc_data = data.copy()
        
        # Mask values outside valid range
        qc_data[qc_data < min_value] = np.nan
        qc_data[qc_data > max_value] = np.nan
        
        # Count valid points
        valid_count = np.sum(~np.isnan(qc_data))
        total_count = qc_data.size
        valid_percent = 100 * valid_count / total_count
        
        logger.info(f"QC complete: {valid_count}/{total_count} "
                   f"({valid_percent:.1f}%) valid points")
        
        return qc_data


# Convenience function
def process_grib2_file(file_path: Path) -> Dict[str, Any]:
    """
    Process a GRIB2 file.
    
    Args:
        file_path: Path to GRIB2 file
        
    Returns:
        Processed data dictionary
    """
    processor = GRIB2Processor()
    return processor.process_file(file_path)

