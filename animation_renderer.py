import re
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from asset_manager import AssetManager

# Initialize asset manager for proper file organization
asset_manager = AssetManager()

def is_float_str(s):
    return bool(re.match(r'^-?\d+(\.\d+)?$', s.strip()))

def is_hex_color(s):
    return bool(re.match(r'^#[0-9A-Fa-f]{6}$', s.strip()))

def hex_to_rgb(h):
    h = h.strip()
    return (int(h[1:3],16), int(h[3:5],16), int(h[5:7],16))

def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

def parse_numeric_list(s):
    parts = re.split(r'[\s,]+', s.strip())
    nums = []
    for p in parts:
        p = p.strip()
        if p and is_float_str(p):
            nums.append(float(p))
        else:
            return None
    return nums

def interpolate(a, b, t):
    return a + (b - a) * t

def interpolate_lists(list_a, list_b, t):
    return [interpolate(x, y, t) for x, y in zip(list_a, list_b)]

def interpolate_color(c1, c2, t):
    return (
        int(c1[0] + (c2[0]-c1[0])*t),
        int(c1[1] + (c2[1]-c1[1])*t),
        int(c1[2] + (c2[2]-c1[2])*t)
    )

class AnimationRenderer:
    def __init__(self, run_dir: str = None):
        self.animations = {}
        self.asset_manager = AssetManager(run_dir=run_dir)

    def create_animation(self, character_name: str, animation_name: str, svg_code: str, output_path: str = None) -> str:
        """
        Create an animated SVG from base SVG

        Args:
            character_name: Name of the character
            animation_name: Name of the animation
            svg_code: Base SVG code to animate
            output_path: Optional output path override

        Returns:
            Path to the generated animated SVG as string
        """
        try:
            # Determine output path
            if not output_path:
                # Use asset manager's default path
                filename = f"{character_name.lower()}_{animation_name.lower()}.svg"
                final_path = self.asset_manager.get_path("animations", filename)
            else:
                # Use provided path but ensure it's properly formatted
                final_path = Path(output_path)

            # Ensure parent directory exists
            final_path.parent.mkdir(parents=True, exist_ok=True)

            # Create animated SVG
            animated_svg = self._add_animations(svg_code)

            # Write file using string path
            str_path = str(final_path)
            with open(str_path, 'w') as f:
                f.write(animated_svg)

            logger.info(f"Generated animated SVG for {character_name}: {str_path}")
            return str_path

        except Exception as e:
            logger.error(f"Failed to create animation for {character_name}: {e}")
            raise

    def _add_animations(self, svg_code: str) -> str:
        """Add animation elements to SVG code"""
        # Extract animation values from SVG
        animated_svg = svg_code

        # Handle translate animations
        translate_pattern = r'values="([^"]*)".*?attributeName="([^"]*)"'
        for values, attr_name in re.findall(translate_pattern, svg_code):
            # Split values string into list of coordinates
            value_list = [x.strip() for x in values.split(';')]
            if len(value_list) >= 2:
                # Parse start and end values
                start_vals = [float(x) if is_float_str(x) else x for x in parse_numeric_list(value_list[0]) or []]
                end_vals = [float(x) if is_float_str(x) else x for x in parse_numeric_list(value_list[1]) or []]

                if start_vals and end_vals and len(start_vals) == len(end_vals):
                    # Add animation elements
                    animated_svg = self._add_transform_animation(
                        animated_svg, 
                        attr_name,
                        start_vals,
                        end_vals
                    )

        # Handle color animations
        color_pattern = r'values="(#[0-9A-Fa-f]{6};#[0-9A-Fa-f]{6})"'
        for values in re.findall(color_pattern, svg_code):
            start_color, end_color = values.split(';')
            if is_hex_color(start_color) and is_hex_color(end_color):
                # Add color animation
                animated_svg = self._add_color_animation(
                    animated_svg,
                    start_color,
                    end_color
                )

        # Handle path animations
        path_pattern = r'd="([^"]*)".*?attributeName="d"'
        for path_values in re.findall(path_pattern, svg_code):
            paths = [p.strip() for p in path_values.split(';')]
            if len(paths) >= 2:
                # Add path animation
                animated_svg = self._add_path_animation(
                    animated_svg,
                    paths[0],
                    paths[1]
                )

        return animated_svg

    def _add_transform_animation(self, svg: str, attr_name: str, start_vals: list, end_vals: list) -> str:
        """Add transform animation to SVG"""
        animation = f"""
            <animateTransform
                attributeName="{attr_name}"
                type="translate"
                dur="1s"
                values="{' '.join(map(str, start_vals))};{' '.join(map(str, end_vals))}"
                repeatCount="indefinite"
            />
        """
        return self._insert_animation(svg, animation)

    def _add_color_animation(self, svg: str, start_color: str, end_color: str) -> str:
        """Add color animation to SVG"""
        animation = f"""
            <animate
                attributeName="fill"
                dur="1s"
                values="{start_color};{end_color}"
                repeatCount="indefinite"
            />
        """
        return self._insert_animation(svg, animation)

    def _add_path_animation(self, svg: str, start_path: str, end_path: str) -> str:
        """Add path animation to SVG"""
        animation = f"""
            <animate
                attributeName="d"
                dur="1s"
                values="{start_path};{end_path}"
                repeatCount="indefinite"
            />
        """
        return self._insert_animation(svg, animation)

    def _insert_animation(self, svg: str, animation: str) -> str:
        """Insert animation element into SVG"""
        closing_tag_pos = svg.rfind('</svg>')
        if closing_tag_pos != -1:
            return svg[:closing_tag_pos] + animation + svg[closing_tag_pos:]
        return svg