import os
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class AssetManager:
    """Manages asset organization and storage for storybook generation runs"""

    def __init__(self, base_dir: str = "output", run_dir: str | None = None):
        """Initialize asset manager with organized directory structure.

        If run_dir is provided, use that. Otherwise, generate a new run_id and create a new run directory.
        """
        # Convert to absolute path and normalize
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized AssetManager with base directory: {self.base_dir}")

        if run_dir is not None:
            # Use the provided run directory
            self.run_dir = Path(run_dir).resolve()
            self.run_id = self.run_dir.name
            logger.info(f"Using provided run directory: {self.run_dir}")
        else:
            # Always generate a new run_id for each pipeline run
            self.run_id = self._generate_run_id()
            self.run_dir = self.base_dir / self.run_id
            logger.info(f"Generated new run ID: {self.run_id}")

        # Create run directory and initialize structure
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Set up run directory: {self.run_dir}")
            self._initialize_run_directory()
        except Exception as e:
            logger.error(f"Failed to initialize directory structure: {e}")
            raise

    def _generate_run_id(self) -> str:
        """Generate a unique run ID using date and a hash."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import hashlib
        hash_str = hashlib.md5(timestamp.encode()).hexdigest()[:8]
        return f"run_{timestamp}_{hash_str}"

    def _initialize_run_directory(self):
        """Create run directory structure with essential subdirectories"""
        subdirs = ["characters", "backgrounds", "animations", "metadata", "scenes", "test_composition"]

        self.dirs = {}
        for subdir in subdirs:
            dir_path = self.run_dir / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            self.dirs[subdir] = dir_path

        # Initialize metadata
        self.metadata = {
            "run_id": self.run_id,
            "created_at": datetime.now().isoformat(),
            "assets": {subdir: [] for subdir in subdirs if subdir != "metadata"}
        }
        self._save_metadata()

    def get_path(self, asset_type: str, filename: str) -> Path:
        """Get full path for an asset file"""
        if asset_type not in self.dirs:
            raise ValueError(f"Unknown asset type: {asset_type}")
        return self.dirs[asset_type] / filename

    def save_story_analysis(self, analysis_data: Dict):
        """Save story analysis data"""
        file_path = self.get_path("metadata", "story_analysis.json")
        with open(file_path, 'w') as f:
            json.dump(analysis_data, f, indent=2)
        self._save_metadata()
        return file_path

    def save_character(self, character_name: str, svg_data: str) -> Path:
        """Save character SVG file"""
        safe_name = self._safe_filename(character_name)
        file_path = self.get_path("characters", f"{safe_name}.svg")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(svg_data)
        self.metadata["assets"]["characters"].append(f"{safe_name}.svg")
        self._save_metadata()
        return file_path

    def save_background(self, scene_id: str, image_data: bytes, format: str = 'png') -> Path:
        """Save background image file"""
        safe_name = self._safe_filename(scene_id)
        filename = f"{safe_name}.{format}"
        file_path = self.get_path("backgrounds", filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'wb') as f:
            f.write(image_data)

        self.metadata["assets"]["backgrounds"].append(filename)
        self._save_metadata()

        logger.info(f"Saved background image to: {file_path}")
        return file_path

    def save_animation(self, character_name: str, animation_name: str, svg_data: str) -> Path:
        """Save character animation SVG"""
        safe_name = self._safe_filename(f"{character_name}_{animation_name}")
        file_path = self.get_path("animations", f"{safe_name}.svg")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(svg_data)
        self.metadata["assets"]["animations"].append(f"{safe_name}.svg")
        self._save_metadata()
        return file_path

    def save_test_composition(self, filename: str, content: str) -> Path:
        """Save test composition file"""
        safe_name = self._safe_filename(filename)
        file_path = self.get_path("test_composition", safe_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(content)
        if "test_composition" not in self.metadata["assets"]:
            self.metadata["assets"]["test_composition"] = []
        self.metadata["assets"]["test_composition"].append(safe_name)
        self._save_metadata()
        return file_path

    def _save_metadata(self):
        """Save metadata to JSON file"""
        metadata_file = self.dirs["metadata"] / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Convert string to safe filename"""
        name = str(name)
        safe = name.lower().strip().replace(" ", "_")
        safe = "".join(c for c in safe if c.isalnum() or c in "_-")
        return safe[:50]
