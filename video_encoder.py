from io import BytesIO
from pathlib import Path
from PIL import Image
import tempfile
import subprocess
import numpy as np
import logging

logger = logging.getLogger(__name__)

class VideoEncoder:
    # Supported formats and their ffmpeg configurations
    FORMAT_CONFIGS = {
        '.mp4': {
            'vcodec': 'libx264',
            'preset': 'medium',
            'crf': '18',  # Lower CRF for better quality (range 0-51, lower is better)
            'pix_fmt': 'yuv420p',
            'movflags': '+faststart',
            'tune': 'animation',  # Optimize for animation content
            'profile:v': 'high',  # Use high profile for better quality
            'level': '4.1'       # Compatible with most devices
        }
    }

    def __init__(self, output_path, fps):
        self.output_path = output_path
        self.fps = fps
        self.format = Path(output_path).suffix.lower()

        if self.format not in self.FORMAT_CONFIGS:
            raise ValueError(f"Unsupported output format: {self.format}. "
                           f"Supported formats: {', '.join(self.FORMAT_CONFIGS.keys())}")

        # Create temporary directory for frames
        self.temp_dir = tempfile.mkdtemp()

    def encode_frames(self, frames):
        """Encode frames into video file using ffmpeg with enhanced quality settings"""
        try:
            if not frames:
                raise ValueError("No frames to encode")

            logger.info(f"Starting video encoding with {len(frames)} frames...")
            frame_paths = []

            # Create temporary directory if it doesn't exist
            temp_dir = Path(self.temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Save frames as temporary PNG files
            for i, frame_data in enumerate(frames, 1):
                try:
                    frame_path = temp_dir / f"frame_{i:06d}.png"
                    with open(frame_path, 'wb') as f:
                        f.write(frame_data)
                    frame_paths.append(frame_path)
                    if i % 10 == 0:  # Log every 10 frames
                        logger.info(f"Saved frame {i}/{len(frames)}")
                except Exception as e:
                    logger.error(f"Failed to save frame {i}: {e}")
                    raise

            logger.info("All frames saved successfully")

            # Verify frames exist
            if not frame_paths:
                raise ValueError("No frames were saved successfully")

            # Get first frame dimensions
            try:
                with Image.open(frame_paths[0]) as img:
                    width, height = img.size
                    # Ensure even dimensions for yuv420p
                    width = (width // 2) * 2
                    height = (height // 2) * 2
                logger.info(f"Frame dimensions: {width}x{height}")
            except Exception as e:
                logger.error(f"Failed to read frame dimensions: {e}")
                raise

            # Build ffmpeg command
            config = self.FORMAT_CONFIGS[self.format]
            ffmpeg_cmd = [
                'ffmpeg',
                '-y',  # Overwrite output file
                '-framerate', str(self.fps),
                '-i', str(temp_dir / 'frame_%06d.png'),
                '-vf', f'scale={width}:{height},format=yuv420p',
                '-vsync', 'cfr',
                '-g', '150',  # Keyframe interval
                '-bf', '2',   # Maximum B-frames
            ]

            # Add format-specific options
            for key, value in config.items():
                if key != 'pix_fmt':  # Skip pix_fmt as we handle it in -vf
                    ffmpeg_cmd.extend([f'-{key}', str(value)])

            # Ensure output directory exists
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)

            # Add output file
            ffmpeg_cmd.append(str(self.output_path))

            # Log command
            logger.info("Executing FFmpeg command:")
            logger.info(' '.join(ffmpeg_cmd))

            # Run FFmpeg with detailed output capture
            try:
                logger.info("Starting FFmpeg encoding process...")
                result = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True,
                    text=True,
                    check=True  # Raise CalledProcessError to catch specific ffmpeg errors
                )
                if result.stderr:
                    logger.info("FFmpeg output:")
                    logger.info(result.stderr)
            except subprocess.CalledProcessError as e:
                logger.error("\nFFmpeg Error Output:")
                logger.error("=" * 40)
                logger.error(e.stderr)
                logger.error("=" * 40)
                raise RuntimeError(f"FFmpeg encoding failed with return code {e.returncode}")

            # Verify output
            if not Path(self.output_path).exists():
                raise RuntimeError("Output file was not created")

            file_size = Path(self.output_path).stat().st_size
            if file_size == 0:
                raise RuntimeError("Output file is empty")

            logger.info(f"Successfully created video: {self.output_path}")
            logger.info(f"Video file size: {file_size / (1024*1024):.2f} MB")

            return self.output_path

        except Exception as e:
            logger.error(f"Video encoding failed: {str(e)}")
            if Path(self.output_path).exists():
                Path(self.output_path).unlink()
            raise

        finally:
            # Clean up temporary files
            try:
                if frame_paths:
                    logger.info("Cleaning up temporary files...")
                    for frame_path in frame_paths:
                        try:
                            frame_path.unlink()
                        except Exception as e:
                            logger.warning(f"Failed to delete temporary frame {frame_path}: {e}")
                if Path(self.temp_dir).exists():
                    import shutil
                    shutil.rmtree(self.temp_dir)
                logger.info("Cleanup completed")
            except Exception as e:
                logger.warning(f"Error during cleanup: {e}")
