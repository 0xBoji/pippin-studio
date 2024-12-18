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
        This method uses an LLM to generate movements for the characters in the scene.
        We have updated the prompt to:
        - Take into account the default SVG size of 1024x1024.
        - Add variety in character scaling and placement.
        - Use at least some movement in at least every other scene (if story context allows).
        - Leverage animations if they are specified as required by the characters in the story analysis.
        - Consider narrative and background description triggers.
        - Keep characters away from extreme edges and generally towards the center.
        - Allow overlapping if narratively appropriate (e.g., hugging), but avoid complete blocking.
        - If one character, consider zooming in or making them large. If multiple characters, scale them down so all fit comfortably.
        - Introduce horizontal/vertical movement, zoom, or positioning variety between scenes.
        """

        scene_id = scene_data["scene_id"]
        narration = scene_data["narration_text"]
        background_desc = scene_data["background_description"]
        background_path = scene_data["background_path"]
        duration = max(scene_duration, 1.0)

        # Gather character names and their required animations
        characters = character_info
        character_names = [c["name"] for c in characters]
        # Extract required_animations from character_info for direct reference
        char_animations_map = {c["name"]: c.get("required_animations", []) for c in characters}

        # Calculate basic character starting positions
        char_positions = self._calculate_character_positions(scene_data, character_names)

        # Prepare schema
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

        # Additional instructions for animations and movement logic
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

        # Updated system instructions:
        system_instructions = f"""
You are a scene movement generation expert. Produce a JSON object describing the scene timeline with character movements and scales, considering the following:

- Canvas is 1024x1024. Keep characters within roughly the inner area, not touching edges. For example, keep positions within about 100 to 924 in both x and y to avoid going off-screen.
- We have {len(character_names)} character(s): {character_names}
- Characters come from story_data analysis and each may have required_animations. These must be considered. The characters and their required_animations are:
  {json.dumps(char_animations_map, indent=2)}
- The scene:
  - scene_id: {scene_id}
  - duration: {duration} (seconds)
  - background_path: {background_path}
  - narration_text: {narration}
  - background_description: {background_desc}
  - pre-calculated positions (suggested starting points): {json.dumps({name: list(pos) for name, pos in char_positions.items()})}

Rules and logic:
1. Scaling and Positioning:
   - If there is only one character, consider zooming in (larger scale, e.g. 1.0 up to 2.0) or placing them prominently in the center. For multiple characters, use smaller scales (0.5 to 1.0) so they all fit comfortably without blocking each other.
   - Introduce variety between scenes. Sometimes zoom in on a character (larger scale near center), other times show them smaller and possibly moving across the scene.
   - Keep characters mostly towards the center. Avoid placing them too close to the edges. Overlapping is allowed if it makes sense (e.g., hugging), but do not let one character completely block another from view.
   - Ensure start and end positions keep characters visible within the 1024x1024 canvas.

2. Movement:
   - Try to have at least one character show noticeable movement every other scene (for example, if scene_id is even, definitely include some movement if possible, unless the story strongly contradicts it).
   - Movement can be horizontal, vertical, diagonal, or a zoom (change in scale).
   - If the story description or character required_animations suggests action, implement that movement.
   - All movements should occur within the scene duration. Start simple: e.g., fade-in scale from near 0.01 to desired scale over the first second, then apply movements or animations.
   - It's okay if some characters remain relatively still, but try to provide visual interest.

3. Animations:
   - Use required_animations from character_info if present. If a character has a required animation, try to incorporate it unless it's nonsensical.
   - Check if background_description or narration_text suggests trigger words for an animation from the list:
     {json.dumps(animation_triggers, indent=2)}
   - If a required_animation is listed for a character, you should include it even if the scene doesn't explicitly trigger it by background words. For example, if a character requires "hop", include a hop sequence.
   - Animation movement patterns:
     - hop: character moves up (y-100) and then returns back down
     - dance: character shifts slightly in x (e.g. +50), then returns
     - wave: character stays in place but has 'wave' animation_name
     - fly: character moves diagonally (x+100,y-100), then back
   - If multiple required_animations exist, you can chain them or pick one. If time allows, include more than one.
   - Each animation should last the specified duration from the animation_durations map, then return the character to original position if it involves position change.

4. Scaling details:
   - Never use scale=0.0. Use at least 0.01 for fade-in.
   - Consider subtle scale changes for interest. For example, start_scale=0.01 and end_scale=1.0 in the first second to "fade in." If zooming in for a close-up, you can go up to 2.0 scale for a single character scenario.

5. Timing:
   - Start with a fade-in from near-zero scale at start_time=0 to normal scale by 1 second.
   - After fade-in, schedule animations (if any). If a character has "fly" animation required, for example, do a fly movement mid-scene.
   - Total scene duration is fixed. Ensure all movements and animations complete by scene end, or at least do not exceed it.

6. JSON output must match the schema provided. If you have multiple movements per character, just list them in the "movements" array in chronological order.

7. If no triggers for a certain animation are found, but the character requires it, perform it anyway. If no animations are required or triggered, you can still do subtle movements for variety (like small shifts in position, or a slight scale change).

Follow these instructions carefully and output only the JSON as per the schema below.

Schema:
{json.dumps(schema, indent=2)}
"""

        # User prompt
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

        # Validate fields
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
