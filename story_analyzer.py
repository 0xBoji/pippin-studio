import asyncio
import json
import logging
from typing import Dict, List
from litellm import completion

logger = logging.getLogger(__name__)

class StoryAnalyzer:
    def __init__(self, generation_mode="prompt", scene_count="auto"):
        # the newest OpenAI model is "gpt-4o"
        self.model = "gpt-4o"
        self.generation_mode = generation_mode
        self.scene_count = scene_count

    async def analyze(self, story_text: str) -> Dict:
        """Analyze story and extract characters, objects, and scenes.
           If generation_mode is 'prompt', the 'story_text' is actually a title + prompt combination 
           and we should first generate a story from it before extracting characters and scenes.
           If generation_mode is 'full_text', the story_text is the full story itself.
        """
        if self.generation_mode == "prompt":
            # Generate a multi-scene story text from the given prompt
            story_text = await self._generate_full_story(story_text)

        characters = await self._extract_characters(story_text)
        scenes = await self._extract_scenes(story_text, characters)
        return {
            "characters": characters,
            "scenes": scenes
        }

    async def _generate_full_story(self, prompt_text: str) -> str:
        """Generate a full story from a title and prompt (the given prompt_text includes both).
           Optionally consider the scene_count to guide how many scenes the story should have.
        """
        instructions = f"""
        You are a storyteller. I will provide a title and a prompt. Generate a cohesive, narrative story text.

        Requirements:
        - The story should be self-contained and complete.
        - If scene_count is a number (not "auto"), structure the story so it can be naturally divided into that many scenes.
        - If scene_count is "auto", you can choose the natural number of scenes.
        - Make sure the story is detailed and suitable for visual scene extraction.

        scene_count: {self.scene_count}

        Respond with the full story text.
        """

        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"Title and prompt:\n\n{prompt_text}"}
        ]

        response = completion(model=self.model, messages=messages, temperature=0.7)
        story = response.choices[0].message.content.strip()
        logger.info("Generated story text from prompt.")
        return story

    async def _extract_characters(self, story_text: str) -> List[Dict]:
        logger.info("Starting character extraction...")

        try:
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
            """

            messages = [
                {
                    "role": "system",
                    "content": "You are a story analysis expert that extracts characters and objects from stories."
                },
                {
                    "role": "user",
                    "content": f"{prompt}\n\nStory text:\n{story_text}"
                }
            ]

            response = completion(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            logger.info(f"Received character extraction response: {content}")

            result = json.loads(content)
            if "characters" not in result or not isinstance(result["characters"], list):
                logger.error("Invalid character extraction response")
                return []
            return result["characters"]

        except Exception as e:
            logger.error(f"Error extracting characters: {e}")
            return []

    async def _extract_scenes(self, story_text: str, characters: List[Dict]) -> List[Dict]:
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

        # If scene_count is auto, no additional constraint. If a number, instruct the model to create exactly that many scenes.
        scene_count_instruction = ""
        if self.scene_count != "auto":
            scene_count_instruction = f"Create exactly {self.scene_count} scenes."

        prompt = f"""
        Analyze this story and break it into scenes, with test criteria for each. The available characters are: {char_list}

        {scene_count_instruction}

        For each scene, provide:
        1. scene_id: Sequential number starting from 0
        2. background_description: A detailed scene description optimized for DALL-E image generation. Do not include any mention of characters from the scene in the background image description as we will overlay that back on later.
        3. characters: List of characters present in the scene
        4. narration_text: The story text for this scene
        5. test_criteria: Specific elements to verify in the generated scene

        Example scene output:
        {json.dumps(scene_example, indent=2)}

        Return a JSON object matching this schema:
        {json.dumps(schema, indent=2)}

        Story text:
        {story_text}
        """

        try:
            response = completion(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a scene analyzer that outputs structured JSON data."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            return result["scenes"]

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse scene extraction response: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting scenes: {e}")
            return []
