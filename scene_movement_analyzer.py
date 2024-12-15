import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import os
from asset_manager import AssetManager
import json

logger = logging.getLogger(__name__)

@dataclass
class CharacterMovement:
    """Represents a single movement/animation for a character"""
    character_name: str
    start_time: float
    end_time: float
    start_position: Tuple[int, int]
    end_position: Tuple[int, int]
    start_scale: float
    end_scale: float
    animation_name: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "character_name": self.character_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_position": list(self.start_position),
            "end_position": list(self.end_position),
            "start_scale": self.start_scale,
            "end_scale": self.end_scale,
            "animation_name": self.animation_name
        }

@dataclass
class SceneTimeline:
    """Contains all movements and timing for a scene"""
    scene_id: int
    duration: float
    background_path: str
    narration_text: str
    movements: List[CharacterMovement]

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "scene_id": self.scene_id,
            "duration": self.duration,
            "background_path": self.background_path,
            "narration_text": self.narration_text,
            "movements": [m.to_dict() for m in self.movements]
        }

# Asset management is handled by the imported AssetManager class

class SceneMovementAnalyzer:
    """Analyzes scene data to determine character movements and timing"""

    # Canvas dimensions (matching DALL-E output)
    CANVAS_WIDTH = 1024
    CANVAS_HEIGHT = 1024

    # Default timing constants
    BASE_DURATION = 3.0
    MIN_DURATION = 5.0
    ANIMATION_DURATION = 1.5

    def __init__(self):
        """Analyzes scene data to determine character movements and timing"""
        self.asset_manager = AssetManager()

    def analyze_scene(self, scene_data: Dict, character_info: List[Dict]) -> SceneTimeline:
        """Generate timeline of movements for a scene"""
        try:
            # Extract scene info
            scene_id = scene_data["scene_id"]
            narration = scene_data["narration_text"]
            background_desc = scene_data["background_description"]

            # Track movements and timing
            movements = []
            current_time = 0.0

            # Get initial positions for all characters
            char_positions = self._calculate_character_positions(
                scene_data,
                [char["name"] for char in character_info]
            )

            # Process each character's movements
            for char_info in character_info:
                char_name = char_info["name"]
                base_pos = char_positions[char_name]

                # Initial appearance with base SVG
                movements.append(CharacterMovement(
                    character_name=char_name,
                    start_time=current_time,
                    end_time=current_time + 1.0,
                    start_position=base_pos,
                    end_position=base_pos,
                    start_scale=0.0,  # Fade in
                    end_scale=1.0,
                    animation_name=None  # Use base SVG
                ))

                # Add required animations with timing offsets
                animation_delay = 0.5  # Delay between animations
                for anim in char_info["required_animations"]:
                    if self._should_use_animation(anim, scene_data):
                        # Calculate animation timing
                        start_time = current_time + 1.0
                        duration = self._get_animation_duration(anim)
                        end_time = start_time + duration

                        # Calculate movement path
                        start_pos = base_pos
                        end_pos = self._calculate_movement_end(base_pos, anim)

                        # Add animation movement
                        movements.append(CharacterMovement(
                            character_name=char_name,
                            start_time=start_time,
                            end_time=end_time,
                            start_position=start_pos,
                            end_position=end_pos,
                            start_scale=1.0,
                            end_scale=1.0,
                            animation_name=anim
                        ))

                        # Add return movement if needed
                        if end_pos != start_pos:
                            movements.append(CharacterMovement(
                                character_name=char_name,
                                start_time=end_time,
                                end_time=end_time + 1.0,
                                start_position=end_pos,
                                end_position=start_pos,
                                start_scale=1.0,
                                end_scale=1.0,
                                animation_name=None  # Use base SVG for return
                            ))

                        current_time = end_time + animation_delay

            # Ensure minimum scene duration
            duration = max(
                self.MIN_DURATION,
                max(mov.end_time for mov in movements) + 1.0
            )

            # Generate the scene timeline
            timeline = SceneTimeline(
                scene_id=scene_id,
                duration=duration,
                background_path=f"scene_{scene_id}_background.png",
                narration_text=narration,
                movements=movements
            )

            output_path = self.asset_manager.get_path("metadata", "scene_movements.json")

            existing_data = []
            if output_path.exists():
                try:
                    with open(output_path, 'r') as f:
                        existing_data = json.load(f)
                    if not isinstance(existing_data, list):
                        # If the file isn't a list, we can transform it into a list
                        # or raise an error. Let's assume we transform it into a list.
                        existing_data = [existing_data]
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse existing {output_path}, starting fresh.")
                    existing_data = []

            # Append the new timeline data
            existing_data.append(timeline.to_dict())

            with open(output_path, 'w') as f:
                json.dump(existing_data, f, indent=4)
            logger.info(f"Updated scene_movements.json with scene {timeline.scene_id}")


            logger.info(f"Generated timeline for scene {scene_id} with {len(movements)} movements and saved to {output_path}")
            return timeline

        except Exception as e:
            logger.error(f"Failed to analyze scene {scene_data.get('scene_id')}: {e}")
            raise

    def _calculate_character_positions(self, scene_data: Dict, characters: List[str]) -> Dict[str, Tuple[int, int]]:
        """Calculate initial positions for characters based on scene context and visual elements"""
        positions = {}
        num_chars = len(characters)

        # Get scene context
        scene_desc = scene_data.get("background_description", "").lower()
        test_criteria = scene_data.get("test_criteria", {})
        visual_elements = test_criteria.get("visual_elements", [])

        # Default layout: spread characters across the lower third of the scene
        base_y = int(self.CANVAS_HEIGHT * 0.7)  # Position in lower third
        spacing = self.CANVAS_WIDTH // (num_chars + 1)

        # Process each character
        for i, char_name in enumerate(characters, 1):
            x_pos = spacing * i
            y_pos = base_y

            # Adjust for specific scene elements
            if any(elem in scene_desc for elem in ["sky", "flying", "soaring"]):
                y_pos = int(self.CANVAS_HEIGHT * 0.3)  # Upper third for flying
            elif any(elem in scene_desc for elem in ["ground", "meadow", "grass"]):
                y_pos = int(self.CANVAS_HEIGHT * 0.8)  # Lower position for ground-based

            # Character-specific adjustments
            if "owl" in char_name.lower() and "perch" in scene_desc:
                y_pos = int(self.CANVAS_HEIGHT * 0.4)  # Perched position

            positions[char_name] = (x_pos, y_pos)

        return positions

    def _get_animation_duration(self, animation: str) -> float:
        """Get the duration for a specific animation type"""
        durations = {
            "hop": 1.0,
            "dance": 2.0,
            "wave": 1.5,
            "fly": 2.5,
            "sparkle": 1.0,
            "glow": 1.5
        }
        return durations.get(animation, self.ANIMATION_DURATION)

    def _should_use_animation(self, animation: str, scene_data: Dict) -> bool:
        """Determine if an animation should be used in this scene context"""
        # Check scene description and test criteria to decide
        description = scene_data["background_description"].lower()

        # Map animations to relevant keywords
        animation_triggers = {
            "hop": ["jump", "hop", "bounce"],
            "dance": ["dance", "celebration", "happy"],
            "wave": ["greet", "wave", "hello"],
            "fly": ["fly", "soar", "glide"]
        }

        return any(trigger in description 
                  for trigger in animation_triggers.get(animation, []))

    def _calculate_movement_end(self, start_pos: Tuple[int, int], animation: str) -> Tuple[int, int]:
        """Calculate ending position for a movement based on animation type"""
        x, y = start_pos

        # Movement patterns for different animations
        patterns = {
            "hop": (x, y - 100),  # Move up
            "dance": (x + 50, y),  # Move slightly right
            "wave": (x, y),        # Stay in place
            "fly": (x + 100, y - 100)  # Move up and right
        }

        return patterns.get(animation, (x, y))