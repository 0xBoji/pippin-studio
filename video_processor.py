#video_processor.py

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

        scene_frames = []
        if scene_svg_path:
            svg_processor = SVGProcessor(Path(scene_svg_path))
            scene_svg_frames = await svg_processor.generate_frames(duration=duration, fps=fps)
            scene_frames = scene_svg_frames

        character_data_list = []
        for char in characters:
            animation_path = Path(char["animation_path"])
            if not animation_path.exists():
                raise FileNotFoundError(f"Character animation file not found: {animation_path}")

            svg_processor = SVGProcessor(animation_path)
            char_duration = max(duration, svg_processor.get_animation_duration())  
            char_frames = await svg_processor.generate_frames(duration=char_duration, fps=fps)
            character_data_list.append({
                'frames': char_frames,
                'movements': char.get('movements', []),
                'name': char.get('name', 'unnamed_character')
            })

        encoder = VideoEncoder(str(output_path), fps)

        final_frames = []
        for frame_idx in range(total_frames):
            current_time = frame_idx / fps
            frame = bg_array.copy()
            # Keep progress logs every 10 frames
            if frame_idx % 10 == 0:
                logger.info(f"Processing frame {frame_idx+1}/{total_frames}")

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

            for char_data in character_data_list:
                frames = char_data['frames']
                if not frames:
                    continue
                char_frame_idx = frame_idx % len(frames)
                char_frame = frames[char_frame_idx]

                cx, cy, scale = self._compute_character_position_scale(char_data['movements'], current_time)

                char_img = Image.open(BytesIO(char_frame)).convert('RGBA')
                if scale != 1.0:
                    new_w = int(char_img.width * scale)
                    new_h = int(char_img.height * scale)
                    char_img = char_img.resize((new_w, new_h), Image.LANCZOS)

                char_array = np.array(char_img)
                ch, cw = char_array.shape[:2]

                x = int(cx - cw/2)
                y = int(cy - ch/2)

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

    def _compute_character_position_scale(self, movements: List[Dict], current_time: float) -> Tuple[float,float,float]:
        if not movements:
            return (512, 512, 1.0)

        current_segment = movements[-1]
        for m in movements:
            if m["start_time"] <= current_time <= m["end_time"]:
                current_segment = m
                break

        start_pos = current_segment.get("start_position")
        end_pos = current_segment.get("end_position")

        if (not start_pos or len(start_pos) != 2 or not end_pos or len(end_pos) != 2):
            logger.warning("Invalid position data in movements. Falling back to center.")
            return (512, 512, 1.0)

        start_t = current_segment["start_time"]
        end_t = current_segment["end_time"]
        if end_t == start_t:
            t = 1.0
        else:
            t = (current_time - start_t) / (end_t - start_t)
            t = max(0.0, min(t, 1.0))

        sx, sy = start_pos
        ex, ey = end_pos
        x = sx + (ex - sx)*t
        y = sy + (ey - sy)*t

        s_start = current_segment.get("start_scale", 1.0)
        s_end = current_segment.get("end_scale", 1.0)
        scale = s_start + (s_end - s_start)*t

        return (x, y, scale)
