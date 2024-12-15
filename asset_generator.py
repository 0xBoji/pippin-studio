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

logger = logging.getLogger(__name__)

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
        # Use the provided asset_manager directly, do not create new runs
        self.model = "gpt-4o"
        self.asset_manager = asset_manager
        try:
            self.client = OpenAI()
            logger.info("OpenAI client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

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
        char_desc = character['description'].lower()
        if not char_name or not isinstance(char_name, str):
            raise ValueError(f"Invalid character name: {char_name}")
        if char_type not in ['character', 'object']:
            raise ValueError(f"Invalid character type: {char_type}")
        if not char_desc:
            raise ValueError(f"Empty character description for {char_name}")

        logger.info(f"Generating base SVG for character: {char_name}")
        if char_type == "character":
            # Generic character SVG
            svg_code = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="250" height="250" viewBox="0 0 250 250" 
    xmlns="http://www.w3.org/2000/svg"
    xmlns:xlink="http://www.w3.org/1999/xlink">
    ... (same unicorn SVG as before) ...
</svg>"""
            # Truncated for brevity; use the same unicorn SVG code from before
            svg_code = svg_code.replace("... (same unicorn SVG as before) ...", """
    <defs>
        <g id="Unicorn_base_character">
            <!-- Steady Legs Group -->
            <g>
                <path d="M100,160 L100,190" stroke="#000" stroke-width="2"/>
                <path d="M120,160 L120,190" stroke="#000" stroke-width="2"/>
                <path d="M140,160 L140,190" stroke="#000" stroke-width="2"/>
                <path d="M160,120 Q165,140 160,160" stroke="#000" stroke-width="2"/>
                <ellipse cx="100" cy="190" rx="5" ry="2" fill="#000"/>
                <ellipse cx="120" cy="190" rx="5" ry="2" fill="#000"/>
                <ellipse cx="140" cy="190" rx="5" ry="2" fill="#000"/>
                <ellipse cx="160" cy="160" rx="5" ry="2" fill="#000"/>
            </g>
            <g>
                <animateTransform attributeName="transform" attributeType="XML" type="translate" values="0 0; 0 15; 0 0" dur="0.8s" repeatCount="indefinite"/>
                <path d="M80,150 Q60,120 80,90 Q100,60 140,70 Q180,80 160,120 Q150,160 100,160 Z" fill="#fff" stroke="#000" stroke-width="2"/>
                <path d="M80,150 Q70,155 75,160 Q70,165 80,170" stroke="#ff69b4" stroke-width="2" fill="none"/>
                <path d="M75,160 Q80,165 75,170" stroke="#ff69b4" stroke-width="2" fill="none"/>
                <path d="M90,120 Q95,110 100,120" stroke="#000" stroke-width="1" fill="none"/>
                <path d="M110,130 Q115,120 120,130" stroke="#000" stroke-width="1" fill="none"/>
            </g>
            <g>
                <animateTransform attributeName="transform" attributeType="XML" type="translate" values="0 0; 0 12; 0 0" dur="0.8s" begin="0.08s" repeatCount="indefinite"/>
                <path d="M140,70 Q150,60 160,55 Q170,50 175,60 Q180,70 170,80 Q160,85 150,80 Q140,75 140,70 Z" fill="#fff" stroke="#000" stroke-width="2"/>
                <polygon points="160,55 155,35 165,35" fill="#ffd700" stroke="#000" stroke-width="1"/>
                <path d="M165,45 Q166,40 160,43" fill="#fff" stroke="#000" stroke-width="1"/>
                <path d="M170,45 Q171,40 165,43" fill="#fff" stroke="#000" stroke-width="1"/>
                <circle cx="162" cy="60" r="3" fill="#000"/>
                <circle cx="158" cy="60" r="1.5" fill="#fff"/>
                <path d="M155,55 Q150,60 155,65 Q150,70 155,75 Q150,80 155,85" stroke="#ff69b4" stroke-width="2" fill="none"/>
                <path d="M160,55 Q155,60 160,65 Q155,70 160,75 Q155,80 160,85" stroke="#ff69b4" stroke-width="2" fill="none"/>
            </g>
        </g>
    </defs>
    <use xlink:href="#Unicorn_base_character"/>
            """)

        else:
            svg_code = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="250" height="250" viewBox="0 0 250 250"
    xmlns="http://www.w3.org/2000/svg"
    xmlns:xlink="http://www.w3.org/1999/xlink">
    <defs>
        <g id="{name}_base_character">
            <rect x="0" y="0" width="200" height="200" fill="#fff" stroke="#000" stroke-width="8"/>
        </g>
    </defs>
    <use xlink:href="#{name}_base_character"/>
</svg>""".format(name=char_name.replace(" ","_"))

        if not svg_code.startswith('<?xml') or '</svg>' not in svg_code:
            raise ValueError(f"Invalid SVG structure for {char_name}")

        return {
            "svg_code": svg_code,
            "character_name": char_name
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

        prompt = f"""
        Create an animated SVG for {character['name']} performing {animation_name} by modifying the base SVG.
        Only add animation elements, preserve structure.
        Base SVG:
        {base_svg}
        """

        response = completion(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an SVG animation expert that returns JSON with animation_svg."
                },
                {
                    "role": "user",
                    "content": f"Return a JSON object matching this schema:\n{json.dumps(schema, indent=2)}\n{prompt}"
                }
            ],
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)
        animation_svg = result["animation_svg"]
        char_name = result["character_name"]
        anim_name = result["animation_name"]

        anim_path = self.asset_manager.save_animation(char_name, anim_name, animation_svg)
        logger.info(f"Animation saved at: {anim_path}")

        return result

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
