import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from io import BytesIO
from PIL import Image
import subprocess
import numpy as np
import cairosvg
import math

from asset_manager import AssetManager
from svg_processor import SVGProcessor
from video_encoder import VideoEncoder

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, asset_manager: AssetManager):
        self.asset_manager = asset_manager

    async def create_scene_video(self, scene_data: Dict, output_path: Optional[Path] = None) -> Path:
        """
        Render the scene video by:
        - Rendering the background scene SVG frames.
        - Rendering each character over it based on movements.
        - For each character's animation, derive its natural duration
          from the first movement in scene_movements.json that uses it.
        """
        scene_id = scene_data["scene_id"]
        duration = scene_data.get("duration", 5.0)
        scene_svg_path = scene_data.get("svg_path", None)
        characters = scene_data.get("characters", [])

        if output_path is None:
            output_path = self.asset_manager.get_path("scenes/video", f"scene_{scene_id}.mp4")

        output_path = output_path.absolute()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        background_path = Path(scene_data["background_path"]).absolute()
        if not background_path.exists():
            raise FileNotFoundError(f"Background image not found: {background_path}")

        with Image.open(background_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            bg_array = np.array(img)

        fps = 30
        total_frames = int(duration * fps)

        # Render scene background frames if any
        scene_frames = []
        if scene_svg_path:
            svg_processor = SVGProcessor(Path(scene_svg_path))
            scene_svg_frames = await svg_processor.generate_frames(duration=duration, fps=fps)
            scene_frames = scene_svg_frames

        # We need to determine animation durations from movements
        # For each character, we have a set of movements with animation_name.
        # We'll find the first movement that uses a given animation_name and use that duration.
        # If an animation_name appears multiple times with different durations, 
        # we stick to the first encountered duration.

        # Gather animation durations from movements
        animation_durations = {}  # { (char_name, anim_name): duration_in_seconds }

        for char_data in characters:
            char_name = char_data["name"]
            for m in char_data["movements"]:
                anim_name = m["animation_name"]
                if anim_name is not None:
                    movement_duration = m["end_time"] - m["start_time"]
                    # If not set yet, record this animation duration
                    if (char_name, anim_name) not in animation_durations:
                        animation_durations[(char_name, anim_name)] = movement_duration

        # Pre-generate frames for each character and their animations
        character_frames_map = {}
        for char_data in characters:
            char_name = char_data["name"]
            base_path = char_data["base_path"]
            animations = char_data["animations"]

            # Base frames: we consider the base character animation equivalent to the entire scene duration
            # since it might be a subtle idle animation. If you prefer, you can set a default duration for base.
            # We'll just keep using scene duration here for base_path for now.
            base_svg_proc = SVGProcessor(Path(base_path))
            base_frames = await base_svg_proc.generate_frames(duration=duration, fps=fps)
            character_frames_map[char_name] = {None: base_frames}

            # Now for each animation, use the calculated duration if available
            for anim_name, anim_svg in animations.items():
                # Determine animation duration
                # If not in animation_durations, default to a 1s duration (or scene duration)
                # Ideally every animation_name should appear in at least one movement, but let's be safe.
                anim_duration = animation_durations.get((char_name, anim_name), 1.0)

                anim_path = self.asset_manager.save_animation(char_name, f"{anim_name}_temp", anim_svg)
                anim_processor = SVGProcessor(Path(anim_path))
                # Generate frames for this specific animation duration
                anim_frames = await anim_processor.generate_frames(duration=anim_duration, fps=fps)
                character_frames_map[char_name][anim_name] = anim_frames

        encoder = VideoEncoder(str(output_path), fps)

        final_frames = []
        for frame_idx in range(total_frames):
            current_time = frame_idx / fps
            frame = bg_array.copy()
            if frame_idx % 10 == 0:
                logger.info(f"Processing frame {frame_idx+1}/{total_frames}")

            # Blend scene frame if available
            if scene_frames:
                scene_frame = scene_frames[min(frame_idx, len(scene_frames)-1)]
                scene_img = Image.open(BytesIO(scene_frame)).convert('RGBA')
                scene_array = np.array(scene_img)

                h, w = frame.shape[:2]
                ch, cw = scene_array.shape[:2]

                x, y = 0, 0
                x2, y2 = min(w, cw), min(h, ch)
                alpha = scene_array[0:y2,0:x2,3:4]/255.0
                src_rgb = scene_array[0:y2,0:x2,:3]
                dst_rgb = frame[0:y2,0:x2]
                blended = (src_rgb*alpha + dst_rgb*(1-alpha)).astype(np.uint8)
                frame[0:y2,0:x2] = blended

            # Place characters based on current movement
            for char_data in characters:
                char_name = char_data["name"]
                char_movements = char_data["movements"]
                current_movement = None
                for m in char_movements:
                    if m["start_time"] <= current_time <= m["end_time"]:
                        current_movement = m
                        break

                if not current_movement:
                    continue

                anim_name = current_movement["animation_name"]
                frames = character_frames_map[char_name].get(anim_name, character_frames_map[char_name][None])
                if not frames:
                    continue

                movement_duration = current_movement["end_time"] - current_movement["start_time"]
                if movement_duration <= 0:
                    movement_duration = 0.001
                t = (current_time - current_movement["start_time"]) / movement_duration
                t = max(0.0, min(t, 1.0))

                # t maps 0->start_time to 1->end_time of that movement
                # frames for this animation were generated according to the movement's animation duration
                # so t directly maps to the frames of that animation
                char_frame_idx = int(t * (len(frames)-1))
                char_frame = frames[char_frame_idx]

                # Determine character position and scale
                sx, sy = current_movement["start_position"]
                ex, ey = current_movement["end_position"]
                x_pos = sx + (ex - sx)*t
                y_pos = sy + (ey - sy)*t

                s_scale = current_movement["start_scale"]
                e_scale = current_movement["end_scale"]
                scale = s_scale + (e_scale - s_scale)*t

                char_img = Image.open(BytesIO(char_frame)).convert('RGBA')
                if scale != 1.0:
                    new_w = int(char_img.width * scale)
                    new_h = int(char_img.height * scale)
                    char_img = char_img.resize((new_w, new_h), Image.LANCZOS)

                char_array = np.array(char_img)
                ch, cw = char_array.shape[:2]

                x = int(x_pos - cw/2)
                y = int(y_pos - ch/2)

                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(frame.shape[1], x+cw), min(frame.shape[0], y+ch)

                src_x1 = max(0, -x)
                src_y1 = max(0, -y)
                src_x2 = src_x1 + (x2 - x1)
                src_y2 = src_y1 + (y2 - y1)

                if (x2 > x1 and y2 > y1 and src_x2 > src_x1 and src_y2 > src_y1 and
                    src_y2 <= ch and src_x2 <= cw):
                    alpha = char_array[src_y1:src_y2, src_x1:src_x2, 3:4]/255.0
                    src_rgb = char_array[src_y1:src_y2, src_x1:src_x2,:3]
                    dst_rgb = frame[y1:y2, x1:x2]
                    blended = (src_rgb*alpha + dst_rgb*(1-alpha)).astype(np.uint8)
                    frame[y1:y2, x1:x2] = blended

            frame_img = Image.fromarray(frame)
            with BytesIO() as bio:
                frame_img.save(bio, format='PNG')
                final_frames.append(bio.getvalue())

        if not final_frames:
            raise ValueError("No frames generated")

        video_path = encoder.encode_frames(final_frames)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Generated video file is empty or not created")

        return video_path
