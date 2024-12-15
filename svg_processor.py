import re
import tempfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

try:
    from lxml import etree
    logger.info("Successfully imported lxml.etree")
except ImportError as e:
    logger.error(f"Failed to import lxml.etree: {e}")
    raise

try:
    import cairosvg
    logger.info("Successfully imported cairosvg")
except ImportError as e:
    logger.error(f"Failed to import cairosvg: {e}")
    raise

class SVGProcessor:
    def __init__(self, svg_path):
        self.svg_path = svg_path
        self.tree = None
        self._load_svg()

    def _load_svg(self):
        """Load and parse SVG file"""
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            self.tree = etree.parse(self.svg_path, parser)
            logger.info(f"Successfully loaded SVG file: {self.svg_path}")
        except Exception as e:
            logger.error(f"Failed to load SVG file: {str(e)}")
            raise

    def get_animation_duration(self):
        """Extract animation duration from SVG"""
        root = self.tree.getroot()

        # Look for animate/animateTransform tags with dur
        durations = []
        for elem in root.xpath(".//*[@dur]"):
            dur_str = elem.get('dur')
            if dur_str.endswith('s'):
                durations.append(float(dur_str[:-1]))
            elif dur_str.endswith('ms'):
                durations.append(float(dur_str[:-2]) / 1000)

        # If no animations found, return default duration
        return max(durations) if durations else 3.0

    def _parse_value(self, value_str):
        """Parse animation value string into numeric or tuple values"""
        if not value_str or value_str.isspace():
            return None

        # Try coordinate pair (x,y)
        parts = value_str.strip().split()
        if len(parts) == 2:
            # Attempt to parse both as floats
            try:
                x = float(parts[0])
                y = float(parts[1])
                return (x, y)
            except ValueError:
                pass

        # If not a pair, try single float
        try:
            return float(value_str.strip())
        except ValueError:
            # Could not parse as float, return None
            return None

    def _interpolate_values(self, start_vals, end_vals, factor):
        """Interpolate between two sets of values"""
        if isinstance(start_vals, tuple) and isinstance(end_vals, tuple):
            # Interpolate coordinate pairs
            sx, sy = start_vals
            ex, ey = end_vals
            return (sx + (ex - sx)*factor, sy + (ey - sy)*factor)
        elif isinstance(start_vals, (int, float)) and isinstance(end_vals, (int, float)):
            # Simple numeric interpolation
            return start_vals + (end_vals - start_vals) * factor
        else:
            # Unsupported type combination
            return start_vals

    def _modify_animation_time(self, time):
        """Modify SVG to show animation at specific time"""
        root = self.tree.getroot()

        # Update all animated elements
        # We look for elements with 'attributeName' and animation parameters
        # Handle both animate and animateTransform
        for elem in root.xpath(".//*[@attributeName]"):
            attr_name = elem.get('attributeName')
            anim_type = elem.tag.split('}')[-1]  # animate or animateTransform
            values_str = elem.get('values')
            from_val = elem.get('from')
            to_val = elem.get('to')

            # Determine duration
            dur_str = elem.get('dur', '1s')
            if dur_str.endswith('s'):
                duration = float(dur_str[:-1])
            elif dur_str.endswith('ms'):
                duration = float(dur_str[:-2]) / 1000
            else:
                duration = 1.0

            # Collect values
            raw_values = []
            if values_str:
                raw_values = [v.strip() for v in values_str.split(';') if v.strip()]
            elif from_val and to_val:
                raw_values = [from_val.strip(), to_val.strip()]

            if len(raw_values) < 2:
                # Not enough values to interpolate
                continue

            # Normalize time
            normalized_time = (time % duration) / duration
            num_segments = len(raw_values) - 1
            segment_time = normalized_time * num_segments
            segment_index = int(segment_time)
            if segment_index >= num_segments:
                segment_index = num_segments - 1
            factor = segment_time - segment_index

            try:
                start_value = self._parse_value(raw_values[segment_index])
                end_value = self._parse_value(raw_values[segment_index + 1])
                if start_value is None or end_value is None:
                    continue
                current_value = self._interpolate_values(start_value, end_value, factor)

                parent = elem.getparent()
                if parent is None:
                    continue

                if anim_type == 'animateTransform':
                    # Handle transform animations specifically
                    transform_type = elem.get('type', '')
                    # Based on transform_type, reconstruct transform string
                    if transform_type == 'translate' and isinstance(current_value, tuple):
                        # current_value is (x,y)
                        parent.set(attr_name, f"translate({current_value[0]},{current_value[1]})")
                    elif transform_type == 'scale' and isinstance(current_value, tuple):
                        # current_value is (sx,sy)
                        parent.set(attr_name, f"scale({current_value[0]},{current_value[1]})")
                    elif transform_type == 'rotate':
                        # Rotate might need additional parameters if original had them
                        # If raw_values had rotate syntax, we must replicate it.
                        # For simplicity, assume just angle interpolation:
                        if isinstance(current_value, (int,float)):
                            # If original rotate had center points,
                            # we must detect them from the first raw value:
                            parts = raw_values[segment_index].split()
                            # Expect something like "angle cx cy"
                            # If not provided, default (0,0)
                            if len(parts) == 3:
                                cx = parts[1]
                                cy = parts[2]
                                parent.set(attr_name, f"rotate({current_value} {cx} {cy})")
                            else:
                                parent.set(attr_name, f"rotate({current_value})")
                    else:
                        # Unsupported transform type or no complex handling needed
                        # If it's a single numeric value and it's translate-like, handle accordingly
                        # If we can't determine how to format it, skip
                        pass
                else:
                    # Normal attribute animation (e.g., color or numeric)
                    # Just set the attribute to the numeric or tuple value
                    # If tuple, join by space
                    if isinstance(current_value, tuple):
                        parent.set(attr_name, f"{current_value[0]} {current_value[1]}")
                    else:
                        parent.set(attr_name, str(current_value))

            except Exception as e:
                logger.warning(f"Error interpolating animation values for {attr_name}: {e}")
                continue

    async def generate_frames(self, duration, fps):
        """Generate frames for the animation"""
        frames = []
        frame_count = int(duration * fps)

        logger.info(f"Generating {frame_count} frames at {fps} FPS")

        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(frame_count):
                time = i / fps
                logger.info(f"Generating frame {i+1}/{frame_count}")

                try:
                    if not self.tree:
                        raise ValueError("SVG not loaded properly")

                    # Modify SVG for current time
                    self._modify_animation_time(time)

                    # Convert SVG to PNG bytes
                    svg_bytes = etree.tostring(self.tree.getroot(), encoding='utf-8', method='xml')
                    png_data = cairosvg.svg2png(
                        bytestring=svg_bytes,
                        output_width=1024,
                        output_height=1024,
                        background_color="rgba(0,0,0,0)",
                        parent_width=1024,
                        parent_height=1024
                    )

                    frames.append(png_data)

                except Exception as e:
                    logger.error(f"Failed to generate frame {i+1}: {e}")
                    logger.exception("Detailed error:")
                    raise

            logger.info("Frame generation complete")

        return frames
