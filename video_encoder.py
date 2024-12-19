#video_encoder.py

from io import BytesIO
from pathlib import Path
from PIL import Image
import tempfile
import subprocess
import numpy as np
import logging

logger = logging.getLogger(__name__)

class VideoEncoder:
    FORMAT_CONFIGS = {
        '.mp4': {
            'vcodec': 'libx264',
            'preset': 'medium',
            'crf': '18',
            'pix_fmt': 'yuv420p',
            'movflags': '+faststart',
            'tune': 'animation',
            'profile:v': 'high',
            'level': '4.1'
        }
    }

    def __init__(self, output_path, fps):
        self.output_path = output_path
        self.fps = fps
        self.format = Path(output_path).suffix.lower()

        if self.format not in self.FORMAT_CONFIGS:
            raise ValueError(f"Unsupported output format: {self.format}. "
                             f"Supported formats: {', '.join(self.FORMAT_CONFIGS.keys())}")

        self.temp_dir = tempfile.mkdtemp()

    def encode_frames(self, frames):
        try:
            if not frames:
                raise ValueError("No frames to encode")

            frame_paths = []

            temp_dir = Path(self.temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)

            for i, frame_data in enumerate(frames, 1):
                try:
                    frame_path = temp_dir / f"frame_{i:06d}.png"
                    with open(frame_path, 'wb') as f:
                        f.write(frame_data)
                    frame_paths.append(frame_path)
                    # Keep progress logs every 10 frames
                    if i % 10 == 0:
                        logger.info(f"Saved frame {i}/{len(frames)}")
                except Exception as e:
                    logger.error(f"Failed to save frame {i}: {e}")
                    raise

            if not frame_paths:
                raise ValueError("No frames were saved successfully")

            try:
                with Image.open(frame_paths[0]) as img:
                    width, height = img.size
                    width = (width // 2) * 2
                    height = (height // 2) * 2
            except Exception as e:
                logger.error(f"Failed to read frame dimensions: {e}")
                raise

            config = self.FORMAT_CONFIGS[self.format]
            ffmpeg_cmd = [
                'ffmpeg',
                '-y',
                '-framerate', str(self.fps),
                '-i', str(temp_dir / 'frame_%06d.png'),
                '-vf', f'scale={width}:{height},format=yuv420p',
                '-vsync', 'cfr',
                '-g', '150',
                '-bf', '2',
            ]

            for key, value in config.items():
                if key != 'pix_fmt':
                    ffmpeg_cmd.extend([f'-{key}', str(value)])

            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            ffmpeg_cmd.append(str(self.output_path))

            try:
                result = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                logger.error("\nFFmpeg Error Output:")
                logger.error("=" * 40)
                logger.error(e.stderr)
                logger.error("=" * 40)
                raise RuntimeError(f"FFmpeg encoding failed with return code {e.returncode}")

            if not Path(self.output_path).exists():
                raise RuntimeError("Output file was not created")

            file_size = Path(self.output_path).stat().st_size
            if file_size == 0:
                raise RuntimeError("Output file is empty")

            return self.output_path

        except Exception as e:
            logger.error(f"Video encoding failed: {str(e)}")
            if Path(self.output_path).exists():
                Path(self.output_path).unlink()
            raise

        finally:
            try:
                if frame_paths:
                    for frame_path in frame_paths:
                        try:
                            frame_path.unlink()
                        except Exception as e:
                            logger.warning(f"Failed to delete temporary frame {frame_path}: {e}")
                if Path(self.temp_dir).exists():
                    import shutil
                    shutil.rmtree(self.temp_dir)
            except Exception as e:
                logger.warning(f"Error during cleanup: {e}")
