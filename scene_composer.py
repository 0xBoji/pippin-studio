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
        """Compose all scenes and return a list of scene_data dicts, each with updated duration and characters."""
        composed_scenes = []
        for i, scene in enumerate(story_data["scenes"]):
            timeline = scene_timelines[i] if i < len(scene_timelines) else None
            svg_string = await self._compose_scene(scene, assets, timeline)

            # Save SVG
            svg_path = self.asset_manager.get_path("scenes/svg", f"scene_{scene['scene_id']}.svg")
            with open(svg_path, 'w') as f:
                f.write(svg_string)
            logger.info(f"Saved composed SVG for scene {scene['scene_id']} to: {svg_path}")

            # Convert original characters to dict format
            original_chars = scene.get("characters", [])
            character_dicts = []
            for char_name in original_chars:
                if not isinstance(char_name, str):
                    logger.warning(f"Character entry {char_name} is not a string. Skipping.")
                    continue
                # If we have a base SVG for this character
                if char_name in assets["characters"]:
                    # Use the character's SVG path as animation_path. No animations means static.
                    animation_path = assets["characters"][char_name]
                    # For position, if no movement info is available, default to center
                    character_dicts.append({
                        "name": char_name,
                        "animation_path": animation_path,
                        "position": (512, 512),
                        "scale": 1.0
                    })
                else:
                    logger.warning(f"No SVG found for character {char_name} in assets. Skipping this character.")

            # Use the timeline's duration to ensure correct scene length
            # If timeline is None, fallback to a default, but normally it shouldn't be.
            scene_duration = timeline.duration if timeline else scene.get("duration", 5.0)

            scene_data = {
                "scene_id": scene["scene_id"],
                "svg": svg_string,
                "svg_path": str(svg_path),
                "duration": scene_duration,  # Use timeline.duration here
                "background_path": scene.get("background_path", ""),
                "audio_path": scene.get("audio_path", ""),
                "audio_duration": scene.get("audio_duration", scene_duration),
                "characters": character_dicts
            }

            composed_scenes.append(scene_data)
            logger.info(f"Completed scene {scene['scene_id']} with duration {scene_duration}s")

        return composed_scenes

    async def create_scene_video(self, scene_data: Dict) -> Path:
        """Create a video for a single scene."""
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
        try:
            if timeline and timeline.movements:
                svg_files = {}
                for movement in timeline.movements:
                    char_name = movement.character_name
                    if char_name in assets["characters"]:
                        svg_path = Path(assets["characters"][char_name])
                        if not svg_path.exists():
                            logger.error(f"SVG file not found for {char_name} at {svg_path}")
                            continue
                        svg_files[char_name] = svg_path

                if svg_files:
                    svg_string, duration = self.combine_svgs(svg_files, timeline)
                    return svg_string
                else:
                    logger.error("No character SVG files found for this scene with movements, returning empty SVG.")
                    return '<?xml version="1.0" encoding="UTF-8"?><svg></svg>'
            else:
                # No movements, just static
                dwg = svgwrite.Drawing(size=("1024px", "1024px"), viewBox="0 0 1024 1024")
                movements_file = self.asset_manager.get_path("metadata", "scene_movements.json")
                logger.info(f"Loading scene movements from: {movements_file}")

                scene_movements = None
                if movements_file.exists():
                    with open(movements_file, 'r') as f:
                        movement_data = json.load(f)
                    scene_movements = next((s for s in movement_data if s["scene_id"] == scene["scene_id"]), None)
                    if scene_movements:
                        logger.info(f"Found movements for scene {scene['scene_id']}")
                    else:
                        logger.warning(f"No movements found for scene {scene['scene_id']}")

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

                character_group = dwg.g(id="character_layer")

                # If we have scene_movements but no timeline-based animation, place characters statically
                if scene_movements:
                    sorted_movements = sorted(scene_movements["movements"], key=lambda m: m["start_position"][1])
                    for movement in sorted_movements:
                        char_name = movement["character_name"]
                        if char_name in assets["characters"]:
                            base_svg_path = Path(assets["characters"][char_name])
                            if not base_svg_path.exists():
                                logger.error(f"Character SVG not found: {base_svg_path}")
                                continue

                            base_svg_code = base_svg_path.read_text()
                            shadow = self._create_shadow_element(movement["start_position"], movement["start_scale"])
                            char_instance_group = dwg.g(
                                transform=f"translate({movement['start_position'][0]},{movement['start_position'][1]}) scale(1)"
                            )
                            # Just add the base SVG as static content
                            # We could embed inline, but let's just do a href since we know the path
                            char_instance_group.add(dwg.image(href=base_svg_path.as_uri(), insert=(0,0), size=("250px","250px")))
                            char_instance_group.add(shadow)
                            character_group.add(char_instance_group)
                            logger.debug(f"Added character {char_name} statically to scene {scene['scene_id']}")

                effects_group = dwg.g(id="effects_layer")
                if scene.get("ambient_effects"):
                    particle_effect = self._create_particle_effect(duration=5, delay=0)
                    effects_group.add(particle_effect)

                dwg.add(character_group)
                dwg.add(effects_group)

                svg_string = dwg.tostring()
                return svg_string

        except Exception as e:
            logger.error(f"Error composing scene {scene.get('scene_id')}: {e}")
            logger.exception("Detailed error traceback:")
            return '<?xml version="1.0" encoding="UTF-8"?><svg></svg>'

    def combine_svgs(self, svg_files: Dict[str, Path], timeline) -> Tuple[str, float]:
        try:
            NSMAP = {
                None: "http://www.w3.org/2000/svg",
                "xlink": "http://www.w3.org/1999/xlink"
            }
            combined_svg = etree.Element("svg", nsmap=NSMAP)
            combined_svg.set("width", "1024")
            combined_svg.set("height", "1024")
            combined_svg.set("viewBox", "0 0 1024 1024")

            defs = etree.SubElement(combined_svg, "defs")

            logger.info("Processing character SVGs and collecting definitions...")
            for char_name, svg_path in svg_files.items():
                tree = etree.parse(str(svg_path))
                char_root = tree.getroot()
                char_defs = char_root.find("{http://www.w3.org/2000/svg}defs")
                if char_defs is not None:
                    for def_elem in list(char_defs):
                        defs.append(def_elem)

            logger.info("Adding character movements...")
            max_duration = 0

            for movement in timeline.movements:
                char_name = movement.character_name
                if char_name not in svg_files:
                    raise KeyError(char_name)
                safe_char_name = char_name.replace(' ', '_')
                instance_group_id = f"{safe_char_name}_instance_1"
                char_group = etree.SubElement(combined_svg, "g", id=instance_group_id)
                transform = f"translate({movement.start_position[0]},{movement.start_position[1]}) scale(1)"
                char_group.set("transform", transform)

                char_visual_group = etree.SubElement(char_group, "g")
                base_char_id = f"{safe_char_name}_base_character"

                use_elem = etree.SubElement(char_visual_group, "use")
                use_elem.set("{http://www.w3.org/1999/xlink}href", f"#{base_char_id}")

                if movement.animation_name:
                    duration = movement.end_time - movement.start_time
                    motion_path = etree.SubElement(char_visual_group, "animateMotion")
                    motion_path.set("dur", f"{duration}s")
                    motion_path.set("begin", f"{movement.start_time}s")
                    motion_path.set("fill", "freeze")
                    motion_path.set("calcMode", "spline")
                    motion_path.set("keySplines", "0.42 0 0.58 1")

                    x1, y1 = movement.start_position
                    x2, y2 = movement.end_position
                    dx = x2 - x1
                    dy = y2 - y1
                    dist = (dx*dx + dy*dy)**0.5
                    arc_height = min(50, dist*0.2)
                    cx = x1 + dx/2
                    cy = min(y1, y2) - arc_height
                    path_data = f"M 0,0 Q {cx-x1},{cy-y1} {dx},{dy}"
                    motion_path.set("path", path_data)

                    max_duration = max(max_duration, movement.end_time)

            svg_string = etree.tostring(combined_svg, pretty_print=True,
                                        xml_declaration=True, encoding="UTF-8")
            return svg_string.decode('utf-8'), max_duration

        except Exception as e:
            logger.error(f"Error in combine_svgs: {e}")
            logger.exception("Detailed error traceback:")
            raise

    def _create_background_element(self, url: str) -> svgwrite.image.Image:
        return svgwrite.image.Image(href=url, insert=(0,0), size=("1920px","1080px"))

    def _create_shadow_element(self, position: Tuple[float,float], scale: float) -> svgwrite.shapes.Ellipse:
        return svgwrite.shapes.Ellipse(
            center=(position[0], position[1]+10),
            r=(30*scale, 10*scale),
            fill="rgba(0,0,0,0.2)",
            filter="url(#blur)"
        )
