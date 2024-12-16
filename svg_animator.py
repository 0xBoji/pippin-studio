from typing import Dict, Tuple, Optional, Any
import svgwrite
from xml.etree import ElementTree as ET
from io import StringIO
import logging
import re

logger = logging.getLogger(__name__)

def parse_transform_values(values_str: str) -> list:
    """Parse transform values string into list of coordinates"""
    return [
        tuple(map(float, pair.strip().split(',')))
        for pair in values_str.split(';')
        if pair.strip()
    ]

class SVGAnimator:
    def create_animated_element(
        self,
        base_svg: str,
        animation_data: Dict[str, Any],
        position: Dict[str, float],
        scale: float,
        start_time: float
    ) -> svgwrite.container.Group:
        """Create an animated SVG element with proper timing and transforms"""
        # Create main group for the animated element
        main_group = svgwrite.container.Group()

        try:
            # Clean and parse the base SVG
            cleaned_svg = self._clean_svg(base_svg)
            root = ET.parse(StringIO(cleaned_svg)).getroot()

            # Create content group for the base SVG elements
            content_group = svgwrite.container.Group()

            # Process all SVG elements
            for child in root.iter():
                if not isinstance(child.tag, str):
                    continue

                tag = child.tag.split('}')[-1]  # Remove namespace if present

                # Create element based on tag type
                element = self._create_svg_element(tag, child.attrib)
                if element:
                    content_group.add(element)

            # Add base content
            main_group.add(content_group)

            # Add animations
            if animation_data:
                if "transform" in animation_data:
                    transform_anim = self._create_transform_animation(
                        animation_data["transform"],
                        start_time
                    )
                    main_group.add(transform_anim)

                if "color" in animation_data:
                    color_anim = self._create_color_animation(
                        animation_data["color"],
                        start_time
                    )
                    main_group.add(color_anim)

            # Apply initial transform
            transform = self._create_transform(position, scale)
            main_group.attribs["transform"] = transform

            return main_group

        except Exception as e:
            logger.error(f"Error creating animated element: {e}")
            # Fallback to basic shape
            rect = svgwrite.shapes.Rect(
                insert=(0, 0),
                size=(100, 100),
                fill='none',
                stroke='black'
            )
            main_group.add(rect)
            return main_group

    def _clean_svg(self, svg: str) -> str:
        """Clean SVG string for parsing"""
        # Remove XML declaration and doctype
        svg = re.sub(r'<\?xml[^>]+\?>', '', svg)
        svg = re.sub(r'<!DOCTYPE[^>]+>', '', svg)
        return svg.strip()

    def _create_svg_element(self, tag: str, attrib: Dict) -> Optional[svgwrite.base.BaseElement]:
        """Create SVG element based on tag type"""
        try:
            if tag == 'path':
                return self._create_path(attrib)
            elif tag == 'circle':
                return self._create_circle(attrib)
            elif tag == 'ellipse':
                return self._create_ellipse(attrib)
            elif tag == 'polygon':
                return self._create_polygon(attrib)
            elif tag == 'rect':
                return self._create_rect(attrib)
        except Exception as e:
            logger.error(f"Error creating {tag} element: {e}")
        return None

    def _create_path(self, attrib: Dict) -> svgwrite.path.Path:
        """Create SVG path element"""
        path = svgwrite.path.Path(d=attrib.get('d', ''))
        self._apply_common_attributes(path, attrib)
        return path

    def _create_circle(self, attrib: Dict) -> svgwrite.shapes.Circle:
        """Create SVG circle element"""
        circle = svgwrite.shapes.Circle(
            center=(float(attrib.get('cx', 0)), float(attrib.get('cy', 0))),
            r=float(attrib.get('r', 0))
        )
        self._apply_common_attributes(circle, attrib)
        return circle

    def _create_ellipse(self, attrib: Dict) -> svgwrite.shapes.Ellipse:
        """Create SVG ellipse element"""
        ellipse = svgwrite.shapes.Ellipse(
            center=(float(attrib.get('cx', 0)), float(attrib.get('cy', 0))),
            r=(float(attrib.get('rx', 0)), float(attrib.get('ry', 0)))
        )
        self._apply_common_attributes(ellipse, attrib)
        return ellipse

    def _create_polygon(self, attrib: Dict) -> svgwrite.shapes.Polygon:
        """Create SVG polygon element"""
        points = attrib.get('points', '').strip().split()
        coords = [
            tuple(map(float, p.split(',')))
            for p in points if ',' in p
        ]
        polygon = svgwrite.shapes.Polygon(points=coords)
        self._apply_common_attributes(polygon, attrib)
        return polygon

    def _create_rect(self, attrib: Dict) -> svgwrite.shapes.Rect:
        """Create SVG rect element"""
        rect = svgwrite.shapes.Rect(
            insert=(float(attrib.get('x', 0)), float(attrib.get('y', 0))),
            size=(float(attrib.get('width', 0)), float(attrib.get('height', 0)))
        )
        self._apply_common_attributes(rect, attrib)
        return rect

    def _apply_common_attributes(self, element: svgwrite.base.BaseElement, attrib: Dict):
        """Apply common SVG attributes to element"""
        if 'fill' in attrib:
            element['fill'] = attrib['fill']
        if 'stroke' in attrib:
            element['stroke'] = attrib['stroke']
        if 'stroke-width' in attrib:
            element['stroke-width'] = attrib['stroke-width']
        if 'opacity' in attrib:
            element['opacity'] = attrib['opacity']

    def create_static_element(
        self,
        base_svg: str,
        position: Dict[str, float],
        scale: float
    ) -> svgwrite.container.Group:
        """Create a static SVG element without animations"""
        group = svgwrite.container.Group()

        # Add base SVG content
        cleaned_svg = self._clean_svg(base_svg)
        group.add(svgwrite.raw(cleaned_svg))

        # Apply transform
        transform = self._create_transform(position, scale)
        group.attribs["transform"] = transform

        return group

    def _create_transform_animation(
        self,
        transform_data: Dict[str, Any],
        start_time: float
    ) -> svgwrite.animate.AnimateTransform:
        """Create transform animation element"""
        try:
            return svgwrite.animate.AnimateTransform(
                attributeName="transform",
                type=transform_data["type"],
                dur=f"{transform_data['duration']}s",
                values=transform_data["values"],
                repeatCount=transform_data.get("repeatCount", "indefinite"),
                begin=transform_data.get("begin", f"{start_time}s"),
                additive=transform_data.get("additive", "sum")
            )
        except Exception as e:
            logger.error(f"Failed to create transform animation: {e}")
            raise

    def _create_color_animation(
        self,
        color_data: Dict[str, Any],
        start_time: float
    ) -> svgwrite.animate.Animate:
        """Create color animation element"""
        try:
            return svgwrite.animate.Animate(
                attributeName="fill",
                dur=f"{color_data['duration']}s",
                values=color_data["values"],
                repeatCount=color_data.get("repeatCount", "indefinite"),
                begin=f"{start_time}s"
            )
        except Exception as e:
            logger.error(f"Failed to create color animation: {e}")
            raise

    def _create_transform(self, position: Dict[str, float], scale: float) -> str:
        """Create transform attribute string"""
        return f"translate({position['x']},{position['y']}) scale({scale})"
