import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import os
import json

from asset_manager import AssetManager
from litellm import completion
from openai import OpenAI
from pydantic import BaseModel

# Suppress PIL debug logs
logging.getLogger("PIL").setLevel(logging.WARNING)
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

# Define Pydantic models for structured parsing
class MovementData(BaseModel):
    character_name: str
    start_time: float
    end_time: float
    start_position: List[float]
    end_position: List[float]
    start_scale: float
    end_scale: float
    animation_name: Optional[str]

class SceneTimelineData(BaseModel):
    scene_id: int
    duration: float
    background_path: str
    narration_text: str
    movements: List[MovementData]


class SceneMovementAnalyzer:
    CANVAS_WIDTH = 1024
    CANVAS_HEIGHT = 1024

    def __init__(self):
        self.asset_manager = AssetManager()
        # Use o1-mini model first, then parse with gpt-4o-mini
        self.model = "o1-mini"
        try:
            self.client = OpenAI()
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    def analyze_scene(self, scene_data: Dict, character_info: List[Dict], scene_duration: float) -> SceneTimeline:
        scene_id = scene_data["scene_id"]
        narration = scene_data["narration_text"]
        background_desc = scene_data["background_description"]
        background_path = scene_data["background_path"]
        duration = max(scene_duration, 1.0)

        characters = character_info
        character_names = [c["name"] for c in characters]
        char_animations_map = {c["name"]: c.get("required_animations", []) for c in characters}

        char_positions = self._calculate_character_positions(scene_data, character_names)

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

        system_instructions = f"""
You are a scene movement generation expert, think of yourself as an expert director of a film. Produce a JSON object describing the scene timeline with character movements and scales, considering the following:

- Canvas is 1024x1024. Keep characters within about 100 to 924 range in x and y.
- Characters: {character_names}
- Characters' required_animations:
{json.dumps(char_animations_map, indent=2)}
- scene_id: {scene_id}
- duration: {duration}
- background_path: {background_path}
- narration_text: {narration}
- background_description: {background_desc}
- suggested starting points: {json.dumps({name: list(pos) for name, pos in char_positions.items()})}

Rules and logic:
1. Scaling and Positioning:
   - Keep characters in the safe zone of 576 and 576 in the center (from 224 to 800 pixels both vertically and horizontally. This means their center should be further in than these outer most coordinates.)
   - If single character, use ~1.0 for full body shot, ~0.7 for far away, and ~2.0 for close up (but always shift left or right and down, not centered). If multiple, smaller scale (0.3-0.4) for far away shots, and medium scale (0.6-0.8) for close ups.
   - Keep characters near center, avoid edges.
   - Slight overlapping of characters is allowed if makes sense, but don't completely block others.
   - Create variety between scenes in terms of scale to keep it interesting.

2. Movement:
   - At least one character moves every other scene if possible. But sometimes both move.
   - Movement can be along x, y, diagonal, or scale change.
   - Implement required_animations if present.

3. Animations:
   - If required_animations present, incorporate them.
   - If triggers from background/narration match known animations (hop, dance, wave, fly), use them.
   - Animations have durations in {animation_durations}.
   - Make sure there are no breaks between the end-time of a characters appearance with the start time of the character animation so we don't have breaks or flashes as we switch between them.

4. Timing:
   - Schedule animations mid-scene if any.

5. Output only the JSON matching schema:
{json.dumps(schema, indent=2)}
"""

        user_prompt = "Generate the scene timeline now."

        # First call: use o1-mini to get raw JSON
        o1_response = completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_prompt}
            ]
        )

        o1_response_content = o1_response.choices[0].message.content

        # Second call: use gpt-4o-mini to parse into structured output
        response = self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": f"Given the following data, format it with the given response format: {o1_response_content}"
                }
            ],
            response_format=SceneTimelineData
        )

        parsed_result = response.choices[0].message.parsed

        movements = []
        for m in parsed_result.movements:
            movements.append(CharacterMovement(
                character_name=m.character_name,
                start_time=m.start_time,
                end_time=m.end_time,
                start_position=(m.start_position[0], m.start_position[1]),
                end_position=(m.end_position[0], m.end_position[1]),
                start_scale=m.start_scale,
                end_scale=m.end_scale,
                animation_name=m.animation_name
            ))

        timeline = SceneTimeline(
            scene_id=parsed_result.scene_id,
            duration=parsed_result.duration,
            background_path=parsed_result.background_path,
            narration_text=parsed_result.narration_text,
            movements=movements
        )

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
        description = scene_data["background_description"].lower()
        triggers = {
            "hop": ["jump", "hop", "bounce"],
            "dance": ["dance", "celebration", "happy"],
            "wave": ["greet", "wave", "hello"],
            "fly": ["fly", "soar", "glide"]
        }
        return any(t in description for t in triggers.get(animation, []))

    def _calculate_movement_end(self, start_pos: Tuple[int, int], animation: str) -> Tuple[int, int]:
        x, y = start_pos
        patterns = {
            "hop": (x, y - 100),
            "dance": (x + 50, y),
            "wave": (x, y),
            "fly": (x + 100, y - 100)
        }
        return patterns.get(animation, (x, y))
