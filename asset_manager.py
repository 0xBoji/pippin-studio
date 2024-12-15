import os
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

class AssetManager:
    """Manages asset organization and storage for storybook generation runs"""

    def __init__(self, base_dir: str = "output", run_dir: str = None):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized AssetManager with base directory: {self.base_dir}")

        if run_dir is not None:
            self.run_dir = Path(run_dir).resolve()
            self.run_id = self.run_dir.name
            logger.info(f"Using provided run directory: {self.run_dir}")
        else:
            self.run_id = self._generate_run_id()
            self.run_dir = self.base_dir / self.run_id
            logger.info(f"Generated new run ID: {self.run_id}")

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_run_directory()

    def _generate_run_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import hashlib
        hash_str = hashlib.md5(timestamp.encode()).hexdigest()[:8]
        return f"run_{timestamp}_{hash_str}"

    def _initialize_run_directory(self):
        # Main subdirectories
        subdirs = ["characters", "backgrounds", "animations", "metadata", "scenes", "test_composition"]
        self.dirs = {}
        for subdir in subdirs:
            dir_path = self.run_dir / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            self.dirs[subdir] = dir_path

        # Additional nested directories inside scenes
        svg_dir = self.dirs["scenes"] / "svg"
        svg_dir.mkdir(parents=True, exist_ok=True)
        self.dirs["scenes/svg"] = svg_dir

        audio_dir = self.dirs["scenes"] / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        self.dirs["scenes/audio"] = audio_dir

        video_dir = self.dirs["scenes"] / "video"
        video_dir.mkdir(parents=True, exist_ok=True)
        self.dirs["scenes/video"] = video_dir

        video_with_sound_dir = self.dirs["scenes"] / "video_with_sound"
        video_with_sound_dir.mkdir(parents=True, exist_ok=True)
        self.dirs["scenes/video_with_sound"] = video_with_sound_dir

        # Add final_video directory
        final_video_dir = self.run_dir / "final_video"
        final_video_dir.mkdir(parents=True, exist_ok=True)
        self.dirs["final_video"] = final_video_dir

        self.metadata = {
            "run_id": self.run_id,
            "created_at": datetime.now().isoformat(),
            "assets": {
                "characters": [],
                "backgrounds": [],
                "animations": [],
                "test_composition": [],
                "scenes": []
            }
        }
        self._save_metadata()

    def get_path(self, asset_type: str, filename: str) -> Path:
        if asset_type not in self.dirs:
            raise ValueError(f"Unknown asset type: {asset_type}")
        return self.dirs[asset_type] / filename

    def save_character(self, character_name: str, svg_data: str) -> Path:
        safe_name = self._safe_filename(character_name)
        file_path = self.get_path("characters", f"{safe_name}.svg")
        with open(file_path, 'w') as f:
            f.write(svg_data)
        self.metadata["assets"]["characters"].append(f"{safe_name}.svg")
        self._save_metadata()
        return file_path

    def save_animation(self, character_name: str, animation_name: str, svg_data: str) -> Path:
        safe_name = self._safe_filename(f"{character_name}_{animation_name}")
        file_path = self.get_path("animations", f"{safe_name}.svg")
        with open(file_path, 'w') as f:
            f.write(svg_data)
        self.metadata["assets"]["animations"].append(f"{safe_name}.svg")
        self._save_metadata()
        return file_path

    def _save_metadata(self):
        metadata_file = self.dirs["metadata"] / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def _safe_filename(self, name: str) -> str:
        name = str(name)
        safe = name.lower().strip().replace(" ", "_")
        safe = "".join(c for c in safe if c.isalnum() or c in "_-")
        return safe[:50]
