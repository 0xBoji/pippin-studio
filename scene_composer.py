import logging
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import os
import svgwrite
from lxml import etree
from asset_manager import AssetManager
from svg_animator import SVGAnimator
from video_processor import VideoProcessor

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SceneComposer:
    def __init__(self, asset_manager: Optional[AssetManager] = None):
        self.animator = SVGAnimator()
        self.asset_manager = asset_manager or AssetManager()
        self.video_processor = VideoProcessor(self.asset_manager)

    async def compose_scenes(self, story_data: Dict, assets: Dict, scene_timelines: List) -> List[Dict]:
        composed_scenes = []
        for i, scene in enumerate(story_data["scenes"]):
            timeline = scene_timelines[i] if i < len(scene_timelines) else None
            svg_string = await self._compose_scene(scene, assets, timeline)

            # Save SVG (background + effects only now)
            svg_path = self.asset_manager.get_path("scenes/svg", f"scene_{scene['scene_id']}.svg")
            with open(svg_path, 'w') as f:
                f.write(svg_string)
            logger.info(f"Saved composed SVG for scene {scene['scene_id']} to: {svg_path}")

            scene_duration = timeline.duration if timeline else scene.get("duration", 5.0)

            # Build character data using timeline movements
            # Instead of placing them in SVG, we store their movements here for video_processor to handle.
            character_dicts = []
            if timeline and timeline.movements:
                # Group movements by character
                movements_by_char = {}
                for m in timeline.movements:
                    char_name = m.character_name
                    if char_name not in movements_by_char:
                        movements_by_char[char_name] = []
                    movements_by_char[char_name].append({
                        "start_time": m.start_time,
                        "end_time": m.end_time,
                        "start_position": list(m.start_position),
                        "end_position": list(m.end_position),
                        "start_scale": m.start_scale,
                        "end_scale": m.end_scale,
                        "animation_name": m.animation_name
                    })

                # For each character in scene, assign the corresponding SVG and movements
                for char_name in scene.get("characters", []):
                    if not isinstance(char_name, str):
                        logger.warning(f"Character entry {char_name} is not a string. Skipping.")
                        continue
                    if char_name in assets["characters"]:
                        animation_path = assets["characters"][char_name]

                        # If character has movements, use them; otherwise just a static position
                        char_movements = movements_by_char.get(char_name, [])
                        character_dicts.append({
                            "name": char_name,
                            "animation_path": animation_path,
                            "movements": char_movements
                        })
                    else:
                        logger.warning(f"No SVG found for character {char_name} in assets. Skipping.")
            else:
                # No timeline-based movements, just place characters statically
                for char_name in scene.get("characters", []):
                    if not isinstance(char_name, str):
                        logger.warning(f"Character entry {char_name} is not a string. Skipping.")
                        continue
                    if char_name in assets["characters"]:
                        animation_path = assets["characters"][char_name]
                        # Default position center if no movements
                        character_dicts.append({
                            "name": char_name,
                            "animation_path": animation_path,
                            "movements": [
                                {
                                    "start_time": 0.0,
                                    "end_time": scene_duration,
                                    "start_position": [512, 512],
                                    "end_position": [512, 512],
                                    "start_scale": 1.0,
                                    "end_scale": 1.0,
                                    "animation_name": None
                                }
                            ]
                        })
                    else:
                        logger.warning(f"No SVG found for character {char_name} in assets. Skipping.")

            scene_data = {
                "scene_id": scene["scene_id"],
                "svg": svg_string,
                "svg_path": str(svg_path),
                "duration": scene_duration,
                "background_path": scene.get("background_path", ""),
                "audio_path": scene.get("audio_path", ""),
                "audio_duration": scene.get("audio_duration", scene_duration),
                "characters": character_dicts
            }

            composed_scenes.append(scene_data)
            logger.info(f"Completed scene {scene['scene_id']} with duration {scene_duration}s")

        return composed_scenes

    async def create_scene_video(self, scene_data: Dict) -> Path:
        output_path = self.asset_manager.get_path("scenes/video", f"scene_{scene_data['scene_id']}.mp4")
        video_path = await self.video_processor.create_scene_video(scene_data, output_path=output_path)
        return video_path

    def _create_particle_effect(self, duration: float, delay: float = 0) -> svgwrite.container.Group:
        try:
            particles = svgwrite.container.Group(id="particles")
            for i in range(5):
                particle = svgwrite.container.Group(id=f"particle_{i}")
                x = random.randint(0, 1000)
                y = random.randint(0, 1000)
                circle = svgwrite.shapes.Circle(center=(x, y), r=5, fill="#FFD700", opacity=0.8)
                particle.add(circle)

                float_anim = svgwrite.animate.AnimateTransform(
                    attributeName="transform",
                    type="translate",
                    values=f"0,0; {random.randint(-50, 50)},{random.randint(-50, 50)}",
                    dur=f"{duration}s",
                    repeatCount="indefinite",
                    additive="sum",
                    begin=f"{delay}s"
                )
                fade_anim = svgwrite.animate.Animate(
                    attributeName="opacity",
                    values="0.8;0.2;0.8",
                    dur=f"{duration}s",
                    repeatCount="indefinite",
                    begin=f"{delay}s"
                )
                scale_anim = svgwrite.animate.AnimateTransform(
                    attributeName="transform",
                    type="scale",
                    values=f"1;{random.uniform(1.2, 1.5)};1",
                    dur=f"{duration*1.2}s",
                    repeatCount="indefinite",
                    additive="sum",
                    begin=f"{delay}s"
                )

                particle.add(float_anim)
                particle.add(fade_anim)
                particle.add(scale_anim)
                particles.add(particle)
            return particles
        except Exception as e:
            logger.error(f"Failed to create particle effect: {e}")
            return svgwrite.container.Group(id="particles")

    async def _compose_scene(self, scene: Dict, assets: Dict, timeline=None) -> str:
        # This method now only creates the background and optional effects.
        # We do NOT place characters here, relying fully on the video_processor overlay step.

        try:
            dwg = svgwrite.Drawing(size=("1024px", "1024px"), viewBox="0 0 1024 1024")

            # Add filters
            try:
                glow_filter = dwg.defs.add(dwg.filter(id="glow"))
                glow_filter.feGaussianBlur(in_="SourceGraphic", stdDeviation="2")

                blur_filter = dwg.defs.add(dwg.filter(id="blur"))
                blur_filter.feGaussianBlur(in_="SourceGraphic", stdDeviation="3")

                composite_filter = dwg.defs.add(dwg.filter(id="composite"))
                composite_filter.feGaussianBlur(in_="SourceGraphic", stdDeviation="1")
                composite_filter.feComponentTransfer().feFuncA(type="linear", slope="0.5")
            except Exception as e:
                logger.error(f"Failed to create SVG filters: {e}")

            bg_url = scene.get("background_path", "")
            background_group = dwg.g(id="background_layer")
            background = self._create_background_element(bg_url)
            fade_in = svgwrite.animate.Animate(
                attributeName="opacity",
                values="0;1",
                dur="0.5s",
                begin="0s",
                fill="freeze"
            )
            background.add(fade_in)
            background_group.add(background)
            dwg.add(background_group)

            effects_group = dwg.g(id="effects_layer")
            if scene.get("ambient_effects"):
                particle_effect = self._create_particle_effect(duration=5, delay=0)
                effects_group.add(particle_effect)

            dwg.add(effects_group)

            svg_string = dwg.tostring()
            return svg_string

        except Exception as e:
            logger.error(f"Error composing scene {scene.get('scene_id')}: {e}")
            logger.exception("Detailed error traceback:")
            return '<?xml version="1.0" encoding="UTF-8"?><svg></svg>'

    def _create_background_element(self, url: str) -> svgwrite.image.Image:
        return svgwrite.image.Image(href=url, insert=(0,0), size=("1920px","1080px"))

    def _create_shadow_element(self, position: Tuple[float,float], scale: float) -> svgwrite.shapes.Ellipse:
        return svgwrite.shapes.Ellipse(
            center=(position[0], position[1]+10),
            r=(30*scale, 10*scale),
            fill="rgba(0,0,0,0.2)",
            filter="url(#blur)"
        )
