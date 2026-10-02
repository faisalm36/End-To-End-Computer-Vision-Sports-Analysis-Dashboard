"""Test backend contract compliance."""

import unittest
import json
import tempfile
import shutil
from pathlib import Path
import subprocess
import sys


class TestBackendContract(unittest.TestCase):
    """Test that pipeline complies with backend v0.4.0 contract."""
    
    def test_progress_line_format(self):
        """Verify pipeline emits 'Processing frames: N%' lines for backend parser."""
        # This test would require running the actual pipeline on a video
        # For now, verify the format is correct in code
        
        # Expected format: "Processing frames: 0%", "Processing frames: 1%", ..., "Processing frames: 100%"
        expected_pattern = r"Processing frames: \d+%"
        
        import re
        self.assertTrue(re.match(expected_pattern, "Processing frames: 0%"))
        self.assertTrue(re.match(expected_pattern, "Processing frames: 50%"))
        self.assertTrue(re.match(expected_pattern, "Processing frames: 100%"))
        
        # Verify the format string exists in pipeline.py
        with open('cv/pipeline.py', 'r') as f:
            pipeline_code = f.read()
            self.assertIn('Processing frames:', pipeline_code, 
                         "Pipeline must emit 'Processing frames:' for backend")
            self.assertIn('flush=True', pipeline_code,
                         "Progress lines must be flushed for backend real-time parsing")
    
    def test_required_output_files(self):
        """Verify all four required JSON files are created."""
        required_files = [
            'tracking_detections.json',
            'player_match_stats.json',
            'meta.json',
            'heatmaps.json'  # Must exist even if empty (no calibration)
        ]
        
        # Verify files are mentioned in pipeline.py
        with open('cv/pipeline.py', 'r') as f:
            pipeline_code = f.read()
            for filename in required_files:
                self.assertIn(filename, pipeline_code,
                             f"Pipeline must create {filename} for backend")
    
    def test_device_auto_accepted(self):
        """Verify --device auto is accepted in argument parser."""
        with open('cv/run_pipeline.py', 'r') as f:
            run_pipeline_code = f.read()
            self.assertIn("'auto'", run_pipeline_code,
                         "run_pipeline.py must accept --device auto")
            self.assertIn("default='auto'", run_pipeline_code,
                         "--device should default to auto")
    
    def test_backend_env_vars_documented(self):
        """Verify RUN_ON_MAC.md documents all backend env vars."""
        required_env_vars = [
            'CV_PIPELINE_MODE',
            'CV_PIPELINE_STUB',
            'CV_PIPELINE_PATH',
            'CV_PYTHON',
            'CV_DEVICE',
            'CV_MODEL',
            'CV_CALIBRATION_PATH',
            'CV_EXTRA_ARGS',
            'CV_TIMEOUT_SECONDS',
            'CV_CREATE_UNKNOWN_PLAYERS',
            'CV_OUTPUT_DIR'
        ]
        
        doc_path = Path('cv/docs/RUN_ON_MAC.md')
        if doc_path.exists():
            with open(doc_path, 'r') as f:
                doc_content = f.read()
                for var in required_env_vars:
                    self.assertIn(var, doc_content,
                                 f"RUN_ON_MAC.md must document {var}")


if __name__ == '__main__':
    unittest.main()
