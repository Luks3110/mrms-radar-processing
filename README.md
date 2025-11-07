# MRMS Radar Processor Backend

Python backend service for processing MRMS weather radar data and generating RALA (Reflectivity at Lowest Altitude) products.

## Features

- **Data Scraper**: Fetches latest GRIB2 files from MRMS server
- **GRIB2 Processor**: Parses meteorological data using MetPy
- **RALA Generator**: Computes reflectivity at lowest altitude
- **REST API**: FastAPI server for serving processed radar data
- **Caching**: Efficient data caching to reduce processing overhead

## Setup

```bash
# Install dependencies using uv
uv pip install -e ".[dev]"

# Or just production dependencies
uv pip install -e .
```

## Development

```bash
# Run the development server
uv run uvicorn src.api:app --reload --host 0.0.0.0 --port 8000

# Run tests
uv run pytest

# Format code
uv run black src/

# Lint
uv run ruff check src/

# Start Jupyter for notebooks
cd ../notebooks
uv run jupyter lab
```

## API Endpoints

### `GET /api/radar/latest`
Get the latest processed radar data

**Response:**
```json
{
  "timestamp": "2025-11-07T20:00:36Z",
  "data_url": "/api/radar/data/20251107-200036",
  "metadata": {
    "bounds": {
      "north": 54.995,
      "south": 20.005,
      "east": -60.005,
      "west": -129.995
    },
    "resolution": 0.01,
    "coverage": "CONUS"
  }
}
```

### `GET /api/radar/data/{timestamp}`
Get processed radar data for a specific timestamp

**Response:** PNG image or JSON with coordinates and values

### `GET /api/radar/list`
List available radar data files

**Query Parameters:**
- `limit`: Number of entries to return (default: 24)
- `start_time`: Start time filter (ISO format)

## Architecture

```
src/
├── api.py          # FastAPI application and routes
├── scraper.py      # MRMS data fetcher
├── processor.py    # GRIB2 parsing with MetPy
├── rala.py         # RALA algorithm implementation
├── cache.py        # Data caching layer
└── utils.py        # Helper functions
```

## Processing Pipeline

1. **Scrape**: Poll MRMS server for new files
2. **Download**: Fetch and decompress GRIB2 files
3. **Parse**: Extract reflectivity data with MetPy
4. **Process**: Generate RALA from multiple elevation angles
5. **Cache**: Store processed data for quick access
6. **Serve**: Provide via REST API

## Environment Variables

Create a `.env` file:

```env
# Server configuration
HOST=0.0.0.0
PORT=8000
DEBUG=true

# Data paths
CACHE_DIR=../cache
DATA_DIR=../data

# MRMS configuration
MRMS_BASE_URL=https://mrms.ncep.noaa.gov/3DRefl/MergedReflectivityQC_00.50
UPDATE_INTERVAL=120  # seconds

# Processing options
MAX_CACHE_SIZE=50  # number of files to keep
RALA_MIN_QUALITY=0.5  # QC threshold
```

## Data Flow

```
MRMS Server → Scraper → GRIB2 File → MetPy Parser → NumPy Array → RALA Generator → Cache → API
```

## GRIB2 Processing Notes

- MRMS files are gzipped GRIB2 format
- Each file contains reflectivity data at 0.50° elevation
- Grid: ~7000x3500 points covering CONUS
- Resolution: ~0.01° (~1km)
- Data type: Float32, units: dBZ
- Missing values: typically encoded as NaN or -999

## RALA Algorithm

The Reflectivity at Lowest Altitude algorithm:

1. Load all available elevation angles for a timestamp
2. For each grid point (lat, lon):
   - Find all valid reflectivity values at different heights
   - Select the value from the lowest altitude
   - Apply quality control thresholds
3. Generate output grid with RALA values
4. Apply smoothing and interpolation if needed

## Performance Considerations

- Use async I/O for downloading files
- Cache parsed GRIB2 data in memory
- Process data in chunks for large grids
- Use NumPy vectorization for RALA calculations
- Consider downsampling for web display (1km → 2-4km)

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Test specific module
uv run pytest tests/test_processor.py -v
```

## License

MIT

