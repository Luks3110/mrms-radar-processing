"""Tests for utility functions."""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import gzip
import shutil

from src.utils import (
    parse_mrms_filename,
    format_timestamp,
    dbz_to_color,
    cleanup_old_files,
    validate_grib2_file,
    decompress_grib2,
)


class TestParseMRMSFilename:
    """Tests for MRMS filename parsing."""

    def test_valid_filename(self):
        """Test parsing a valid MRMS filename."""
        filename = "MRMS_MergedReflectivityQC_00.50_20251107-200036.grib2.gz"
        result = parse_mrms_filename(filename)
        
        assert result is not None
        assert result.year == 2025
        assert result.month == 11
        assert result.day == 7
        assert result.hour == 20
        assert result.minute == 0
        assert result.second == 36

    def test_without_gz_extension(self):
        """Test parsing filename without .gz extension."""
        filename = "MRMS_MergedReflectivityQC_00.50_20251107-200036.grib2"
        result = parse_mrms_filename(filename)
        
        assert result is not None
        assert result.year == 2025

    def test_invalid_filename(self):
        """Test parsing an invalid filename."""
        filename = "invalid_filename.txt"
        result = parse_mrms_filename(filename)
        
        assert result is None

    def test_invalid_date(self):
        """Test parsing filename with invalid date."""
        filename = "MRMS_MergedReflectivityQC_00.50_20251399-250070.grib2"
        result = parse_mrms_filename(filename)
        
        assert result is None


class TestFormatTimestamp:
    """Tests for timestamp formatting."""

    def test_format_timestamp(self):
        """Test formatting a datetime to MRMS format."""
        dt = datetime(2025, 11, 7, 20, 0, 36)
        result = format_timestamp(dt)
        
        assert result == "20251107-200036"

    def test_format_timestamp_single_digits(self):
        """Test formatting with single digit values."""
        dt = datetime(2025, 1, 5, 8, 5, 9)
        result = format_timestamp(dt)
        
        assert result == "20250105-080509"


class TestDbzToColor:
    """Tests for dBZ to color conversion."""

    def test_transparent_low_dbz(self):
        """Test that low dBZ values are transparent."""
        color = dbz_to_color(0)
        assert color[3] == 0  # Alpha channel should be 0 (transparent)

    def test_light_blue_range(self):
        """Test light blue color for drizzle range."""
        color = dbz_to_color(10)
        assert color[3] > 0  # Should be visible

    def test_red_heavy_rain(self):
        """Test red color for heavy rain."""
        color = dbz_to_color(55)
        assert color[0] == 255  # Red channel
        assert color[3] == 255  # Fully opaque

    def test_magenta_extreme(self):
        """Test magenta for extreme values."""
        color = dbz_to_color(70)
        assert color[0] > 150  # Red component
        assert color[2] > 150  # Blue component
        assert color[3] == 255  # Fully opaque


class TestCleanupOldFiles:
    """Tests for file cleanup utility."""

    def test_cleanup_no_files(self):
        """Test cleanup with no files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            removed = cleanup_old_files(Path(tmpdir), max_files=10)
            assert removed == 0

    def test_cleanup_below_limit(self):
        """Test cleanup when below limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create 5 files
            for i in range(5):
                (tmpdir_path / f"file_{i}.txt").touch()
            
            removed = cleanup_old_files(tmpdir_path, max_files=10)
            assert removed == 0
            assert len(list(tmpdir_path.glob("*"))) == 5

    def test_cleanup_above_limit(self):
        """Test cleanup when above limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create 10 files
            for i in range(10):
                file_path = tmpdir_path / f"file_{i}.txt"
                file_path.touch()
            
            removed = cleanup_old_files(tmpdir_path, max_files=5)
            assert removed == 5
            assert len(list(tmpdir_path.glob("*"))) == 5


class TestValidateGrib2File:
    """Tests for GRIB2 file validation."""

    def test_nonexistent_file(self):
        """Test validation of non-existent file."""
        result = validate_grib2_file(Path("/nonexistent/file.grib2"))
        assert result is False

    def test_valid_grib2_file(self):
        """Test validation of valid GRIB2 file."""
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tmp:
            # Write GRIB magic bytes
            tmp.write(b"GRIB")
            tmp.write(b"\x00" * 100)  # Dummy data
            tmp_path = Path(tmp.name)
        
        try:
            result = validate_grib2_file(tmp_path)
            assert result is True
        finally:
            tmp_path.unlink()

    def test_invalid_grib2_file(self):
        """Test validation of invalid GRIB2 file."""
        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tmp:
            # Write invalid magic bytes
            tmp.write(b"INVALID")
            tmp_path = Path(tmp.name)
        
        try:
            result = validate_grib2_file(tmp_path)
            assert result is False
        finally:
            tmp_path.unlink()


class TestDecompressGrib2:
    """Tests for GRIB2 decompression."""

    def test_decompress_grib2(self):
        """Test decompression of gzipped GRIB2 file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create a test file
            test_data = b"GRIB" + b"\x00" * 100
            compressed_path = tmpdir_path / "test.grib2.gz"
            
            # Compress it
            with gzip.open(compressed_path, "wb") as f:
                f.write(test_data)
            
            # Decompress
            decompressed_path = decompress_grib2(compressed_path)
            
            # Verify
            assert decompressed_path.exists()
            assert decompressed_path.suffix == ".grib2"
            
            with open(decompressed_path, "rb") as f:
                content = f.read()
                assert content == test_data

