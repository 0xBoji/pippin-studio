import logging
from pathlib import Path
from typing import List, Dict, Optional
from io import BytesIO
from PIL import Image
import subprocess

logger = logging.getLogger(__name__)

try:
    import numpy as np
    logger.info("Successfully imported numpy")
except ImportError as e:
    logger.error(f"Failed to import numpy: {e}")
    raise

try:
    import cv2
    logger.info("Successfully imported OpenCV")
except ImportError as e:
    logger.warning("OpenCV not available, falling back to PIL and ffmpeg")
    cv2 = None

try:
    import cairosvg
    logger.info("Successfully imported cairosvg")
except ImportError as e:
    logger.error(f"Failed to import cairosvg: {e}")
    raise

from asset_manager import AssetManager
from svg_processor import SVGProcessor
from video_encoder import VideoEncoder

class VideoProcessor:
    def __init__(self, asset_manager: AssetManager):
        self.asset_manager = asset_manager

    async def create_scene_video(self, scene_data: Dict, output_path: Optional[Path] = None) -> Path:
        scene_id = scene_data["scene_id"]
        duration = scene_data.get("duration", 5.0)
        # Instead of relying on characters, we now have the main scene SVG to overlay
        scene_svg_path = scene_data.get("svg_path", None)
        characters = scene_data.get("characters", [])

        logger.info(f"Creating video for scene {scene_id} with duration {duration}s")

        output_path = Path("output/scene_test.mp4") if output_path is None else Path(output_path)
        output_path = output_path.absolute()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Video will be saved to: {output_path}")

        background_path = Path(scene_data["background_path"]).absolute()
        if not background_path.exists():
            raise FileNotFoundError(f"Background image not found: {background_path}")

        logger.info(f"Using background image: {background_path}")

        with Image.open(background_path) as img:
            logger.info(f"Background image loaded: {background_path}")
            logger.info(f"Image size: {img.size}")
            logger.info(f"Image mode: {img.mode}")
            logger.info(f"Image format: {img.format}")

        fps = 30
        logger.info(f"Creating video for scene {scene_id} at {fps} FPS")

        # Load background
        with Image.open(background_path) as bg_img:
            if bg_img.mode != 'RGB':
                bg_img = bg_img.convert('RGB')
            bg_array = np.array(bg_img)
            logger.info(f"Converted background to array with shape: {bg_array.shape}")

        scene_frames = []
        if scene_svg_path:
            # Convert scene SVG to frames
            logger.info(f"Converting scene SVG to frames: {scene_svg_path}")
            svg_processor = SVGProcessor(Path(scene_svg_path))
            # scene SVG should match scene duration
            scene_svg_frames = await svg_processor.generate_frames(duration=duration, fps=fps)

            # scene SVG frames will be full 1024x1024 frames (assuming the SVG is the full scene)
            # We'll overlay them directly at (0,0)
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
            # Start with background frame
            frame = bg_array.copy()
            if frame_idx % 10 == 0:
                logger.info(f"Processing frame {frame_idx+1}/{total_frames}")

            # Overlay scene SVG frame if available
            if scene_frames:
                scene_frame = scene_frames[frame_idx % len(scene_frames)]
                scene_img = Image.open(BytesIO(scene_frame)).convert('RGBA')
                scene_array = np.array(scene_img)

                # Overlay at (0,0)
                h, w = frame.shape[:2]
                ch, cw = scene_array.shape[:2]

                # If scene frames match 1024x1024, just overlay directly
                x, y = 0, 0
                x2, y2 = min(w, cw), min(h, ch)
                alpha = scene_array[0:y2,0:x2,3:4]/255.0
                src_rgb = scene_array[0:y2,0:x2,:3]
                dst_rgb = frame[0:y2,0:x2]
                blended = (src_rgb*alpha + dst_rgb*(1-alpha)).astype(np.uint8)
                frame[0:y2,0:x2] = blended

            # Overlay character frames if needed (only if you're still using characters)
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

    def _convert_svg_to_png(self, svg_path: Path, temp_dir: Path) -> Path:
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"{svg_path.stem}.png"
        cairosvg.svg2png(url=str(svg_path), write_to=str(output_path),
                         output_width=1024, output_height=1024,
                         background_color="rgba(0,0,0,0)", scale=1.0)

        with Image.open(output_path) as img:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            new_img = Image.new('RGBA', img.size, (0,0,0,0))
            new_img.paste(img, (0,0), img)
            new_img.save(output_path, 'PNG', optimize=True)

            logger.info(f"Converted SVG to PNG: {output_path} with mode {new_img.mode}")
        return output_path

    def _create_basic_video(self, image_path: Path, output_path: Path, duration: float) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
            "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p",
            "-vf", "scale=1024:1024:force_original_aspect_ratio=decrease,pad=1024:1024:(ow-iw)/2:(oh-ih)/2",
            "-preset", "medium", "-tune", "stillimage", "-crf", "23", "-movflags", "+faststart",
            str(output_path)
        ]
        logger.info("Creating basic video with ffmpeg")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # no changes here
