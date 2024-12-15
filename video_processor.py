import logging
from pathlib import Path
from typing import List, Dict, Optional
from io import BytesIO
from PIL import Image
import subprocess
import numpy as np
import cairosvg

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

        logger.info(f"Creating video for scene {scene_id} with duration {duration}s")

        # If output_path not provided, use scenes/video
        if output_path is None:
            output_path = self.asset_manager.get_path("scenes/video", f"scene_{scene_id}.mp4")

        output_path = output_path.absolute()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Video will be saved to: {output_path}")

        background_path = Path(scene_data["background_path"]).absolute()
        if not background_path.exists():
            raise FileNotFoundError(f"Background image not found: {background_path}")

        logger.info(f"Using background image: {background_path}")
        with Image.open(background_path) as img:
            logger.info(f"Background image loaded: {background_path} size={img.size} mode={img.mode} format={img.format}")

        fps = 30
        logger.info(f"Creating video for scene {scene_id} at {fps} FPS")

        with Image.open(background_path) as bg_img:
            if bg_img.mode != 'RGB':
                bg_img = bg_img.convert('RGB')
            bg_array = np.array(bg_img)
            logger.info(f"Converted background to array with shape: {bg_array.shape}")

        scene_frames = []
        if scene_svg_path:
            logger.info(f"Converting scene SVG to frames: {scene_svg_path}")
            svg_processor = SVGProcessor(Path(scene_svg_path))
            scene_svg_frames = await svg_processor.generate_frames(duration=duration, fps=fps)
            scene_frames = scene_svg_frames

        character_frames = []
        if characters:
            logger.info(f"Processing {len(characters)} character animations...")
            for char in characters:
                animation_path = Path(char["animation_path"])
                if not animation_path.exists():
                    raise FileNotFoundError(f"Character animation file not found: {animation_path}")

                logger.info(f"Processing character animation: {animation_path}")
                svg_processor = SVGProcessor(animation_path)
                char_duration = svg_processor.get_animation_duration()
                frames = await svg_processor.generate_frames(duration=char_duration, fps=fps)

                character_frames.append({
                    'frames': frames,
                    'position': char['position'],
                    'scale': char.get('scale', 1.0),
                    'name': char.get('name', 'unnamed_character')
                })
                logger.info(f"Generated {len(frames)} frames for character: {char.get('name', 'unnamed')}")

        encoder = VideoEncoder(str(output_path), fps)
        logger.info("VideoEncoder initialized successfully")

        final_frames = []
        total_frames = int(duration * fps)
        for frame_idx in range(total_frames):
            frame = bg_array.copy()
            if frame_idx % 10 == 0:
                logger.info(f"Processing frame {frame_idx+1}/{total_frames}")

            if scene_frames:
                scene_frame = scene_frames[frame_idx % len(scene_frames)]
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

            for char_data in character_frames:
                frames = char_data['frames']
                if not frames:
                    continue
                char_frame_idx = frame_idx % len(frames)
                char_frame = frames[char_frame_idx]

                char_img = Image.open(BytesIO(char_frame))
                if char_img.mode != 'RGBA':
                    char_img = char_img.convert('RGBA')
                char_array = np.array(char_img)

                x, y = char_data['position']
                h, w = frame.shape[:2]
                ch, cw = char_array.shape[:2]

                x = int(x - cw/2)
                y = int(y - ch/2)

                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(w, x+cw), min(h, y+ch)

                src_x1 = max(0, -x)
                src_y1 = max(0, -y)
                src_x2 = src_x1 + (x2 - x1)
                src_y2 = src_y1 + (y2 - y1)

                if (x2> x1 and y2>y1 and src_x2>src_x1 and src_y2>src_y1 and src_y2<=ch and src_x2<=cw):
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

        logger.info(f"Encoding {len(final_frames)} frames to {output_path}")
        video_path = encoder.encode_frames(final_frames)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Generated video file is empty or not created")

        logger.info(f"Successfully created video: {output_path}")
        return video_path
