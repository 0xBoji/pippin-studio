import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import os
from asset_manager import AssetManager
import json

from litellm import completion

logger = logging.getLogger(__name__)

@dataclass
class CharacterMovement:
    character_name: str
    start_time: float
    end_time: float
    start_position: Tuple[int, int]
    end_position: Tuple[int, int]
    start_scale: float
    end_scale: float
    animation_name: Optional[str] = None

    def to_dict(self):
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
    scene_id: int
    duration: float
    background_path: str
    narration_text: str
    movements: List[CharacterMovement]

    def to_dict(self):
        return {
            "scene_id": self.scene_id,
            "duration": self.duration,
            "background_path": self.background_path,
            "narration_text": self.narration_text,
            "movements": [m.to_dict() for m in self.movements]
        }

class SceneMovementAnalyzer:
    CANVAS_WIDTH = 1024
    CANVAS_HEIGHT = 1024

    def __init__(self):
        self.asset_manager = AssetManager()
        self.model = "gpt-4o"

    def analyze_scene(self, scene_data: Dict, character_info: List[Dict], scene_duration: float) -> SceneTimeline:
        """
        Now we use an LLM call to generate the movements deterministically based on:
        - Characters and their required animations
        - Scene description
        - Scene duration
        - Logic:
          1) Position characters based on environment keywords.
          2) Initial fade-in with small start scale (e.g., 0.01 to 1.0) over 1s to avoid zero-size issues.
          3) Add animations only if triggered by scene description keywords.
          4) If movement animations occur (like 'fly'), move character from start_pos to end_pos, then back.
          5) Respect scene_duration as the final duration.
          6) Return a JSON object with the structure:
             {
               "scene_id": int,
               "duration": float,
               "background_path": str,
               "narration_text": str,
               "movements": [
                 {
                   "character_name": str,
                   "start_time": float,
                   "end_time": float,
                   "start_position": [float, float],
                   "end_position": [float, float],
                   "start_scale": float,
                   "end_scale": float,
                   "animation_name": str or null
                 }, ...
               ]
             }
        """

        scene_id = scene_data["scene_id"]
        narration = scene_data["narration_text"]
        background_desc = scene_data["background_description"]
        background_path = scene_data["background_path"]
        duration = max(scene_duration, 1.0)

        # Calculate character starting positions
        char_positions = self._calculate_character_positions(scene_data, [c["name"] for c in character_info])

        # Determine possible animations and their triggers
        animation_triggers = {
            "hop": ["jump", "hop", "bounce"],
            "dance": ["dance", "celebration", "happy"],
            "wave": ["greet", "wave", "hello"],
            "fly": ["fly", "soar", "glide"]
        }
        animation_durations = {
            "hop": 1.0,
            "dance": 2.0,
            "wave": 1.5,
            "fly": 2.5,
            "sparkle": 1.0,
            "glow": 1.5
        }

        # Small utility function to produce a fallback scale if needed
        # We'll tell the LLM what logic to follow, so no direct code needed here.
        # Just rely on the instructions.

        # Schema for the final output
        schema = {
            "type": "object",
            "properties": {
                "scene_id": {"type": "integer"},
                "duration": {"type": "number"},
                "background_path": {"type": "string"},
                "narration_text": {"type": "string"},
                "movements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character_name": {"type": "string"},
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                            "start_position": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2
                            },
                            "end_position": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2
                            },
                            "start_scale": {"type": "number"},
                            "end_scale": {"type": "number"},
                            "animation_name": {"type": ["string","null"]}
                        },
                        "required": ["character_name", "start_time", "end_time", "start_position", "end_position", "start_scale", "end_scale", "animation_name"]
                    }
                }
            },
            "required": ["scene_id", "duration", "background_path", "narration_text", "movements"]
        }

        # System instructions for the LLM
        system_instructions = f"""
You are a scene movement generation expert. Your job is to produce a JSON object describing the scene timeline with character movements.

Rules:
- Input:
  - scene_id: {scene_id}
  - duration: {duration}
  - background_path: {background_path}
  - narration_text: {narration}
  - background_description: {background_desc}
  - characters: {json.dumps(character_info)}
  - character_positions: {json.dumps({name: list(pos) for name, pos in char_positions.items()})}

- For each character:
  1) Check character's required_animations and the background_description. If background_description contains trigger words for an animation, schedule that animation after the fade-in. Use the durations:
    {json.dumps(animation_durations, indent=2)}

  For animations that move characters:
    - "hop": end_position is start_position but y decreased by 100.
    - "dance": end_position is start_position plus 50 in x direction.
    - "wave": end_position same as start_position (just animateName set).
    - "fly": end_position is start_position plus (100 in x, -100 in y).

  After performing a movement animation that changes position, return the character to their original position with another movement of 1 second, maintaining scale=1.0.

- Never use scale=0.0. Use at least 0.01 if scaling up or down from near zero.
- Only include animations if triggers are present in background_description.
- If no triggers for an animation are found, do not include that animation.
- Times are cumulative.
- The final scene duration is given. Movements can end before the scene_duration.
- Produce a JSON object exactly matching the schema. 
- The "movements" array can have multiple entries per character. Keep them simple and linear.

You must output a JSON object matching this schema:
{json.dumps(schema, indent=2)}
"""

        # User prompt content
        user_prompt = "Generate the scene timeline now."

        # Run LLM completion
        response = completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        # Parse the result into our SceneTimeline object
        # Validate we got all fields
        if ("scene_id" not in result or
            "duration" not in result or
            "background_path" not in result or
            "narration_text" not in result or
            "movements" not in result):
            raise ValueError("LLM did not return the expected structure.")

        movements = []
        for m in result["movements"]:
            movements.append(CharacterMovement(
                character_name=m["character_name"],
                start_time=m["start_time"],
                end_time=m["end_time"],
                start_position=tuple(m["start_position"]),
                end_position=tuple(m["end_position"]),
                start_scale=m["start_scale"],
                end_scale=m["end_scale"],
                animation_name=m["animation_name"]
            ))

        timeline = SceneTimeline(
            scene_id=result["scene_id"],
            duration=result["duration"],
            background_path=result["background_path"],
            narration_text=result["narration_text"],
            movements=movements
        )

        # Save to scene_movements.json
        output_path = self.asset_manager.get_path("metadata", "scene_movements.json")
        existing_data = []
        if output_path.exists():
            try:
                with open(output_path, 'r') as f:
                    existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    existing_data = [existing_data]
            except json.JSONDecodeError:
                logger.warning(f"Could not parse existing {output_path}, starting fresh.")
                existing_data = []

        existing_data.append(timeline.to_dict())
        with open(output_path, 'w') as f:
            json.dump(existing_data, f, indent=4)
        logger.info(f"Updated scene_movements.json with scene {timeline.scene_id}")

        logger.info(f"Generated timeline for scene {scene_id} with {len(movements)} movements and saved to {output_path}")
        return timeline

    def _calculate_character_positions(self, scene_data: Dict, characters: List[str]) -> Dict[str, Tuple[int, int]]:
        scene_desc = scene_data.get("background_description", "").lower()
        test_criteria = scene_data.get("test_criteria", {})
        positions = {}
        num_chars = len(characters)
        base_y = int(self.CANVAS_HEIGHT * 0.7)
        spacing = self.CANVAS_WIDTH // (num_chars + 1)
        for i, char_name in enumerate(characters, 1):
            x_pos = spacing * i
            y_pos = base_y
            if any(word in scene_desc for word in ["sky", "flying", "soaring"]):
                y_pos = int(self.CANVAS_HEIGHT * 0.3)
            elif any(word in scene_desc for word in ["ground", "meadow", "grass"]):
                y_pos = int(self.CANVAS_HEIGHT * 0.8)
            if "owl" in char_name.lower() and "perch" in scene_desc:
                y_pos = int(self.CANVAS_HEIGHT * 0.4)
            positions[char_name] = (x_pos, y_pos)
        return positions

    def _get_animation_duration(self, animation: str) -> float:
        # Not used anymore, but we keep it if we ever need logic here.
        # The logic is now handled by LLM instructions.
        durations = {
            "hop": 1.0,
            "dance": 2.0,
            "wave": 1.5,
            "fly": 2.5,
            "sparkle": 1.0,
            "glow": 1.5
        }
        return durations.get(animation, 1.5)

    def _should_use_animation(self, animation: str, scene_data: Dict) -> bool:
        # Also not directly needed since LLM does logic,
        # but we keep it for reference if we want to double-check.
        description = scene_data["background_description"].lower()
        triggers = {
            "hop": ["jump", "hop", "bounce"],
            "dance": ["dance", "celebration", "happy"],
            "wave": ["greet", "wave", "hello"],
            "fly": ["fly", "soar", "glide"]
        }
        return any(t in description for t in triggers.get(animation, []))

    def _calculate_movement_end(self, start_pos: Tuple[int, int], animation: str) -> Tuple[int, int]:
        # Also handled by LLM instructions now.
        x, y = start_pos
        patterns = {
            "hop": (x, y - 100),
            "dance": (x + 50, y),
            "wave": (x, y),
            "fly": (x + 100, y - 100)
        }
        return patterns.get(animation, (x, y))
