import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List
import requests
from io import BytesIO
from PIL import Image
from asset_manager import AssetManager
from litellm import completion
from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Define structured output models for parsing
class CharacterSVG(BaseModel):
    svg_code: str
    character_name: str

class AnimationResult(BaseModel):
    animation_svg: str
    character_name: str
    animation_name: str

async def download_image(url: str, output_path: str) -> bool:
    try:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        session = requests.Session()
        retries = requests.adapters.Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]
        )
        session.mount('http://', requests.adapters.HTTPAdapter(max_retries=retries))
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=retries))

        response = session.get(url, timeout=(5, 30))
        response.raise_for_status()

        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            raise ValueError(f"Expected image content type, got {content_type}")

        image = Image.open(BytesIO(response.content))
        image.verify()  
        image = Image.open(BytesIO(response.content))

        if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
            image = image.convert('RGB')

        image.save(str(output_path), format='PNG', optimize=True)
        logger.info(f"Successfully downloaded and saved image to: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Unexpected error while downloading image: {e}")
        return False

class AssetGenerator:
    def __init__(self, asset_manager: AssetManager):
        # Use o1-mini model instead of gpt-4o
        self.model = "o1-mini"
        self.asset_manager = asset_manager
        try:
            self.client = OpenAI()
            logger.info("OpenAI client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

        # Example SVGs from a config-like dictionary
        self.svg_config = {
            "unicorn": """<?xml version="1.0" encoding="UTF-8"?>
<svg width="250" height="250" viewBox="0 0 250 250"
    xmlns="http://www.w3.org/2000/svg"
    xmlns:xlink="http://www.w3.org/1999/xlink">
    <defs>
        <g id="Unicorn_base_character">
            <!-- Base shape with a light bounce animation -->
            <g>
                <animateTransform attributeName="transform" attributeType="XML" type="translate"
                                  values="0 0; 0 15; 0 0" dur="1s" repeatCount="indefinite"/>
                <path d="M80,150 Q60,120 80,90 Q100,60 140,70 Q180,80 160,120 Q150,160 100,160 Z"
                      fill="#fff" stroke="#000" stroke-width="2"/>
                <circle cx="120" cy="110" r="5" fill="#000"/>
                <polygon points="160,55 155,35 165,35" fill="#ffd700" stroke="#000" stroke-width="1"/>
            </g>
        </g>
    </defs>
    <use xlink:href="#Unicorn_base_character"/>
</svg>"""
        }

    async def generate_all_assets(self, story_data: Dict) -> Dict:
        results = []
        character_svgs = {}

        try:
            logger.info("Starting asset generation process...")
            logger.info(f"Found {len(story_data.get('characters', []))} characters to process")

            if not isinstance(story_data, dict):
                raise ValueError("story_data must be a dictionary")

            if "characters" not in story_data:
                raise ValueError("story_data must contain 'characters' key")

            if not isinstance(story_data["characters"], list):
                raise ValueError("story_data['characters'] must be a list")

            # Generate character SVGs
            for character in story_data.get("characters", []):
                char_name = character["name"]
                logger.info(f"Generating base SVG for character: {char_name}")
                char_result = await self.generate_character_svg(character)

                svg_code = char_result.get("svg_code", "")
                if not svg_code or not svg_code.strip().startswith('<?xml'):
                    raise ValueError(f"Invalid base SVG generated for {char_name}")

                svg_path = self.asset_manager.save_character(char_name, svg_code)
                logger.info(f"Successfully saved character SVG to: {svg_path}")
                char_result["svg_path"] = str(svg_path)
                character_svgs[char_name] = svg_code
                results.append(char_result)

                logger.info(f"Successfully generated base SVG for {char_name}")

            missing_chars = [
                char["name"] for char in story_data["characters"]
                if char["name"] not in character_svgs
            ]
            if missing_chars:
                raise ValueError(f"Failed to generate base SVGs for characters: {missing_chars}")

            logger.info("\nStarting animation generation phase...")
            total_animations = sum(
                len(char.get("required_animations", [])) for char in story_data.get("characters", [])
            )
            logger.info(f"Found {total_animations} total animations to generate")

            animation_count = 0
            for character in story_data.get("characters", []):
                char_name = character["name"]
                logger.info(f"\nProcessing animations for character: {char_name}")
                base_svg = character_svgs.get(char_name)
                if not base_svg:
                    logger.error(f"Missing base SVG for character: {char_name}")
                    continue

                if "required_animations" not in character or not isinstance(character["required_animations"], list):
                    logger.warning(f"No or invalid animations defined for character: {char_name}")
                    continue

                for animation in character["required_animations"]:
                    logger.info(f"Starting generation of {animation} animation for {char_name}")
                    anim_result = await self.generate_animation(
                        character=character,
                        animation_name=animation,
                        base_svg=base_svg
                    )

                    animation_svg = anim_result.get("animation_svg", "")
                    if not animation_svg.strip().startswith('<?xml'):
                        raise ValueError(f"Invalid animation SVG generated for {char_name}: {animation}")
                    if '<animate' not in animation_svg and '<animateTransform' not in animation_svg:
                        raise ValueError(f"No animation elements found in SVG for {char_name}: {animation}")

                    animation_count += 1
                    logger.info(f"Successfully generated {animation} animation for {char_name}")
                    results.append(anim_result)
                    logger.info(f"Progress: {animation_count}/{total_animations} animations generated")

            logger.info("Generating backgrounds...")
            if "scenes" in story_data:
                if not isinstance(story_data["scenes"], list):
                    raise ValueError("story_data['scenes'] must be a list")
                for scene in story_data["scenes"]:
                    if "background_description" not in scene:
                        raise ValueError(f"Missing background_description in scene: {scene}")

                    scene_id = scene["scene_id"]
                    background_result = await self.generate_background(scene_id, scene["background_description"])
                    background_result["scene_id"] = scene_id
                    results.append(background_result)

            return self._organize_results(results)

        except Exception as e:
            logger.error(f"Asset generation failed: {e}")
            logger.exception("Detailed error traceback:")
            raise

    async def generate_character_svg(self, character: Dict) -> Dict:
        required_fields = ['name', 'type', 'description', 'required_animations']
        missing_fields = [f for f in required_fields if f not in character]
        if missing_fields:
            raise ValueError(f"Missing required fields in character data: {missing_fields}")

        char_name = character['name']
        char_type = character['type']
        char_desc = character['description']
        if not char_name or not isinstance(char_name, str):
            raise ValueError(f"Invalid character name: {char_name}")
        if char_type not in ['character', 'object']:
            raise ValueError(f"Invalid character type: {char_type}")
        if not char_desc:
            raise ValueError(f"Empty character description for {char_name}")

        # Check if character name matches "unicorn"
        if "unicorn" in char_name.lower():
            svg_code = self.svg_config["unicorn"]
            return {
                "svg_code": svg_code,
                "character_name": char_name
            }
        else:
            # Dynamically generate SVG using o1-mini and then parse with gpt-4o-mini
            schema = {
                "type": "object",
                "properties": {
                    "svg_code": {"type": "string"},
                    "character_name": {"type": "string"}
                },
                "required": ["svg_code", "character_name"]
            }

            system_instructions = """
You are an SVG character generation expert. Given a character's name and description, produce a detailed SVG representing the character that:

- Starts with <?xml version="1.0" encoding="UTF-8"?>.
- Has a single <svg> root with a viewBox and width/height attributes.
- Depicts a character described by the given text (physical appearance, colors).
- Include a subtle 'light bounce' animation (vertical translate) that loops indefinitely.
- No external images or references.
- Include <defs> and a <g> element with an id like {character_name}_base_character.
- Always include this in the svg tag:  xmlns:xlink="http://www.w3.org/1999/xlink"
- After the <defs>, use <use xlink:href="#{character_name}_base_character"/> to display.
- The animation should use <animateTransform> with 'translate' and at least two intermediate values (e.g., values="0 0; 0 10; 0 0") and dur="1s" repeatCount="indefinite".
- Make sure the SVG is valid and can be parsed easily. Keep it under a few hundred lines.
- The output should be a JSON object with "svg_code" and "character_name".
"""

            user_prompt = f"""
Return a JSON object matching this schema:
{json.dumps(schema, indent=2)}

Character name: {char_name}
Character type: {char_type}
Description: {char_desc}

Generate a base animated SVG following the system instructions.
"""

            # First call with o1-mini to get raw JSON
            o1_response = completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": user_prompt}
                ]
            )

            o1_response_content = o1_response.choices[0].message.content

            # Second call with gpt-4o-mini to parse the JSON
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"Given the following data, format it with the given response format: {o1_response_content}"
                    }
                ],
                response_format=CharacterSVG
            )

            parsed_result = response.choices[0].message.parsed
            return {
                "svg_code": parsed_result.svg_code,
                "character_name": parsed_result.character_name
            }

    async def generate_animation(self, character: Dict, animation_name: str, base_svg: str) -> Dict:
        schema = {
            "type": "object",
            "properties": {
                "animation_svg": {"type": "string"},
                "character_name": {"type": "string"},
                "animation_name": {"type": "string"}
            },
            "required": ["animation_svg", "character_name", "animation_name"]
        }

        system_instructions = """
You are an SVG animation expert. Given a base character SVG and an animation_name, add or modify the SVG to include an additional animation representing that action. Follow these rules:

- Do not remove existing elements or animations, only add or augment them.
- Use standard SVG animation elements (<animate>, <animateTransform>, <animateMotion>) with simple, linear values.
- Ensure the resulting SVG is still valid and starts with <?xml version="1.0" encoding="UTF-8"?> and one <svg> root.
- The new animation should be easily parsed: numeric values, hex colors, or transforms.
- Respect the schema: return JSON with "animation_svg", "character_name", "animation_name".
- Keep the style consistent and do not add external resources.
- If the animation_name suggests a particular action, reflect it with a suitable transform or attribute animation.
"""

        user_prompt = f"""
Return a JSON object matching this schema:
{json.dumps(schema, indent=2)}

Character name: {character['name']}
Animation name: {animation_name}

Base SVG:
{base_svg}

Add an animation for '{animation_name}' action following system instructions.
"""

        # First call with o1-mini to get raw JSON
        o1_response = completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_prompt}
            ]
        )

        o1_response_content = o1_response.choices[0].message.content

        # Second call with gpt-4o-mini to parse the JSON
        response = self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": f"Given the following data, format it with the given response format: {o1_response_content}"
                }
            ],
            response_format=AnimationResult
        )

        parsed_result = response.choices[0].message.parsed
        animation_svg = parsed_result.animation_svg
        char_name = parsed_result.character_name
        anim_name = parsed_result.animation_name

        anim_path = self.asset_manager.save_animation(char_name, anim_name, animation_svg)
        logger.info(f"Animation saved at: {anim_path}")

        return {
            "animation_svg": animation_svg,
            "character_name": char_name,
            "animation_name": anim_name
        }

    async def generate_background(self, scene_id: int, description: str) -> Dict:
        result = {
            "description": description,
            "prompt": "",
            "success": False,
            "error": None,
            "url": None,
            "file_path": None
        }

        try:
            result["prompt"] = (
                f"Create a storybook illustration: {description} "
                "Children's book style, bright, colorful, magical, no text."
            )

            image_filename = f"scene_{scene_id}_background.png"
            image_path = self.asset_manager.get_path("backgrounds", image_filename)

            logger.info(f"Generating DALL-E image for scene {scene_id}...")
            logger.info(f"Output path: {image_path}")

            response = self.client.images.generate(
                model="dall-e-3",
                prompt=result["prompt"],
                n=1,
                size="1024x1024",
                quality="standard",
                style="vivid"
            )
            if not response.data:
                raise ValueError("No image data returned")

            image_url = response.data[0].url
            if not image_url:
                raise ValueError("No URL in DALL-E response")

            logger.info(f"Generated image: {image_url}")
            result["url"] = image_url

            if await download_image(image_url, str(image_path)):
                logger.info(f"Image saved to: {image_path}")
                result["file_path"] = str(image_path)
                result["success"] = True
            else:
                raise RuntimeError("Failed to download and save image")

        except Exception as e:
            error_msg = f"Background generation error: {e}"
            logger.error(error_msg)
            result["error"] = error_msg

        return result

    def _organize_results(self, results: List) -> Dict:
        assets = {
            "characters": {},
            "animations": {},
            "backgrounds": []
        }

        for result in results:
            if "animation_name" in result:
                char_name = result["character_name"]
                if char_name not in assets["animations"]:
                    assets["animations"][char_name] = {}
                assets["animations"][char_name][result["animation_name"]] = result["animation_svg"]
            elif "svg_path" in result:
                assets["characters"][result["character_name"]] = result["svg_path"]
            else:
                # background
                if result.get("success"):
                    assets["backgrounds"].append(result)

        return assets
