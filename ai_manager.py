import asyncio
import os
from typing import Dict, List, Any, Optional, Callable
import json
import logging
from pathlib import Path
from litellm import completion
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class AIManager:
    def __init__(self, model: str = "gpt-4o-mini"):
        """Initialize AI manager with default model"""
        self.model = model
        # Validate OpenAI API key
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set. Please provide your OpenAI API key.")
        self.openai_client = OpenAI(api_key=api_key)
        self.semaphore = asyncio.Semaphore(5)  # Limit concurrent AI requests

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def get_structured_completion(
        self,
        prompt: str,
        schema: Dict,
        system_prompt: Optional[str] = None
    ) -> Dict:
        """Get structured completion from LiteLLM"""
        async with self.semaphore:
            try:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})

                messages.append({"role": "user", "content": prompt})

                response = await completion(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    schema=schema
                )

                return json.loads(response.choices[0].message.content)

            except Exception as e:
                logger.error(f"Error in structured completion: {e}")
                raise

    async def generate_dall_e_image(
        self,
        prompt: str,
        size: str = "1024x1024"
    ) -> str:
        """Generate image using DALL-E"""
        async with self.semaphore:
            try:
                response = self.openai_client.images.generate(
                    model="dall-e-3",
                    prompt=prompt,
                    n=1,
                    size=size
                )
                return response.data[0].url

            except Exception as e:
                logger.error(f"Error generating DALL-E image: {e}")
                raise


    async def generate_character_description(self, character_name: str) -> Dict:
        """Generate detailed character description for SVG creation"""
        prompt = f"""
        Create a detailed description for the character '{character_name}' that can be used
        for SVG generation. Include:
        - Visual characteristics
        - Color scheme
        - Style elements
        - Proportions
        - Any distinctive features

        Return as JSON with the following structure:
        {{
            "physical_description": string,
            "color_scheme": {{
                "primary": string,
                "secondary": string,
                "accent": string
            }},
            "proportions": {{
                "height_ratio": float,
                "width_ratio": float
            }},
            "distinctive_features": [string]
        }}
        """

        schema = {
            "type": "object",
            "properties": {
                "physical_description": {"type": "string"},
                "color_scheme": {
                    "type": "object",
                    "properties": {
                        "primary": {"type": "string"},
                        "secondary": {"type": "string"},
                        "accent": {"type": "string"}
                    }
                },
                "proportions": {
                    "type": "object",
                    "properties": {
                        "height_ratio": {"type": "number"},
                        "width_ratio": {"type": "number"}
                    }
                },
                "distinctive_features": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }

        return await self.get_structured_completion(prompt, schema)

    async def generate_animation_description(
        self,
        character_name: str,
        animation_type: str
    ) -> Dict:
        """Generate animation description for a character"""
        prompt = f"""
        Create a detailed description for the animation '{animation_type}'
        for character '{character_name}'. Include:
        - Keyframes and timing
        - Movement patterns
        - Transformation details

        Return as JSON with the following structure:
        {{
            "keyframes": [
                {{
                    "time": float,
                    "transform": string,
                    "easing": string
                }}
            ],
            "duration": float,
            "repeat": boolean
        }}
        """

        schema = {
            "type": "object",
            "properties": {
                "keyframes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "time": {"type": "number"},
                            "transform": {"type": "string"},
                            "easing": {"type": "string"}
                        }
                    }
                },
                "duration": {"type": "number"},
                "repeat": {"type": "boolean"}
            }
        }

        return await self.get_structured_completion(prompt, schema)

    async def generate_scene_timeline(
        self,
        scene_description: str,
        characters: List[str]
    ) -> Dict:
        """Generate detailed scene timeline"""
        prompt = f"""
        Create a detailed timeline for the scene with description:
        {scene_description}

        Available characters: {', '.join(characters)}

        Return as JSON with the following structure:
        {{
            "duration": float,
            "events": [
                {{
                    "time": float,
                    "character": string,
                    "action": string,
                    "position": {{"x": float, "y": float}},
                    "scale": float
                }}
            ]
        }}
        """

        schema = {
            "type": "object",
            "properties": {
                "duration": {"type": "number"},
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "time": {"type": "number"},
                            "character": {"type": "string"},
                            "action": {"type": "string"},
                            "position": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"}
                                }
                            },
                            "scale": {"type": "number"}
                        }
                    }
                }
            }
        }

        return await self.get_structured_completion(prompt, schema)
