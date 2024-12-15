import asyncio
import json
import logging
from typing import Dict, List
from litellm import completion

logger = logging.getLogger(__name__)

class StoryAnalyzer:
    def __init__(self):
        # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        self.model = "gpt-4o"

    async def analyze(self, story_text: str) -> Dict:
        """Analyze story and extract characters, objects, and scenes"""
        characters = await self._extract_characters(story_text)
        scenes = await self._extract_scenes(story_text, characters)
        return {
            "characters": characters,
            "scenes": scenes
        }

    async def _extract_characters(self, story_text: str) -> List[Dict]:
        """Extract characters and objects from story text"""
        logger.info("Starting character extraction...")

        try:
            # Enable JSON schema validation
            import litellm
            litellm.enable_json_schema_validation = True
            litellm.set_verbose = True

            prompt = """
            Analyze the following story and extract all characters and significant objects. For each one, provide:
            1. name: A clear, descriptive name
            2. type: Either "character" or "object"
            3. description: A detailed physical description focused on visual elements that can be rendered in SVG (shape, colors, distinctive features)
            4. required_animations: List of required animations based on their actions in the story

            Return a JSON object with this exact structure:
            {
                "characters": [
                    {
                        "name": "string",
                        "type": "string",
                        "description": "string",
                        "required_animations": ["string"]
                    }
                ]
            }

            Example:
            {
                "characters": [
                    {
                        "name": "Hoppy",
                        "type": "character",
                        "description": "A cheerful bunny with long ears, white fur, and pink nose. Wears a blue bowtie. Has big expressive eyes.",
                        "required_animations": ["hop", "dance", "wave"]
                    }
                ]
            }
            """

            messages = [
                {
                    "role": "system",
                    "content": "You are a story analysis expert that extracts characters and objects from stories, providing detailed structured data for visualization and testing."
                },
                {
                    "role": "user",
                    "content": f"{prompt}\n\nStory text:\n{story_text}"
                }
            ]

            logger.info("Sending request to LiteLLM...")
            response = completion(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            logger.info(f"Received response: {content}")

            try:
                result = json.loads(content)
                if not isinstance(result, dict):
                    logger.error(f"Expected dict, got {type(result)}")
                    return []

                if "characters" not in result:
                    logger.error("Response missing 'characters' key")
                    logger.error(f"Full response: {result}")
                    return []

                characters = result["characters"]
                if not isinstance(characters, list):
                    logger.error(f"Expected characters to be a list, got {type(characters)}")
                    return []

                # Validate each character
                valid_characters = []
                required_fields = ["name", "type", "description", "required_animations"]

                for char in characters:
                    if not isinstance(char, dict):
                        logger.error(f"Invalid character format: {char}")
                        continue

                    # Check required fields
                    if all(field in char for field in required_fields):
                        # Validate type
                        if char["type"] not in ["character", "object"]:
                            logger.error(f"Invalid type for character {char['name']}: {char['type']}")
                            continue

                        # Validate animations list
                        if not isinstance(char["required_animations"], list):
                            logger.error(f"Invalid animations format for {char['name']}")
                            continue

                        valid_characters.append(char)
                    else:
                        logger.error(f"Missing required fields in character: {char}")

                logger.info(f"Successfully extracted {len(valid_characters)} valid characters")
                return valid_characters

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse response JSON: {e}")
                logger.error(f"Raw content: {content}")
                return []
            except Exception as e:
                logger.error(f"Unexpected error processing characters: {e}")
                logger.error(f"Raw content: {content}")
                return []

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse character extraction response: {e}")
            logger.error(f"Raw response content: {response.choices[0].message.content}")
            raise
        except Exception as e:
            logger.error(f"Error extracting characters: {e}")
            logger.error(f"Error details: {str(e)}")
            return []

    async def _extract_scenes(self, story_text: str, characters: List[Dict]) -> List[Dict]:
        """Extract scene information from story text"""
        schema = {
            "type": "object",
            "properties": {
                "scenes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "scene_id": {"type": "integer"},
                            "background_description": {"type": "string"},
                            "characters": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "narration_text": {"type": "string"},
                            "test_criteria": {
                                "type": "object",
                                "properties": {
                                    "visual_elements": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "character_presence": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "mood": {"type": "string"},
                                    "lighting": {"type": "string"}
                                },
                                "required": ["visual_elements", "character_presence", "mood", "lighting"]
                            }
                        },
                        "required": ["scene_id", "background_description", "characters", 
                                   "narration_text", "test_criteria"]
                    }
                }
            },
            "required": ["scenes"]
        }

        char_names = [char["name"] for char in characters]
        char_list = ", ".join(char_names)

        scene_example = {
            "scene_id": 0,
            "background_description": "A whimsical forest clearing bathed in soft morning sunlight, with ancient oak trees forming a natural archway. Colorful wildflowers dot the dewy grass while golden rays filter through the canopy, creating a magical atmosphere with dancing light motes. The scene is rendered in a classic storybook illustration style with soft, dreamy colors and gentle details.",
            "characters": ["Hoppy"],
            "narration_text": "Once upon a time, there was a cheerful bunny named Hoppy who lived in a cozy forest.",
            "test_criteria": {
                "visual_elements": ["oak trees", "wildflowers", "forest clearing", "morning sunlight", "natural archway"],
                "character_presence": ["Hoppy"],
                "mood": "cheerful and whimsical",
                "lighting": "soft morning sunlight with golden rays"
            }
        }

        prompt = f"""
        Analyze this story and break it into scenes, with test criteria for each. The available characters are: {char_list}

        For each scene, provide:
        1. scene_id: Sequential number starting from 0
        2. background_description: A detailed scene description optimized for DALL-E image generation. For each scene:
           - Time and Lighting: Explicitly state time of day and lighting conditions (e.g., "bathed in soft morning sunlight", "golden sunset rays filtering through trees")
           - Environment: Describe key physical elements (e.g., "ancient oak trees with gnarled branches", "meadow filled with colorful wildflowers")
           - Atmosphere: Capture the mood and magical elements (e.g., "mystical forest clearing with floating sparkles", "enchanted woodland with twinkling lights")
           - Artistic Style: Specify "storybook illustration style with soft, whimsical colors in the style of classic children's books"
           Make the description vivid but focused, around 2-3 sentences.
        3. characters: List of characters present in the scene
        4. narration_text: The story text for this scene
        5. test_criteria: Specific elements to verify in the generated scene:
           - visual_elements: List of key visual elements that must be present
           - character_presence: List of characters that must be visible
           - mood: Overall mood/atmosphere of the scene
           - lighting: Specific lighting condition to verify

        Example scene output:
        {json.dumps(scene_example, indent=2)}

        Return a JSON object matching this schema:
        {json.dumps(schema, indent=2)}
        """

        try:
            # Use completion synchronously as per LiteLLM docs
            response = completion(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a scene analyzer that outputs structured JSON data."
                    },
                    {
                        "role": "user",
                        "content": f"""Return a JSON object matching this schema:
{json.dumps(schema, indent=2)}

{prompt}

Story text:
{story_text}"""
                    }
                ],
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            return result["scenes"]

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse scene extraction response: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting scenes: {e}")
            return []