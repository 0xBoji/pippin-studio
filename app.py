from flask import Flask, render_template, request, jsonify, send_file
import asyncio
import os
import threading
from pathlib import Path
import json
import logging

from asset_manager import AssetManager
from ai_manager import AIManager
from story_analyzer import StoryAnalyzer
from asset_generator import AssetGenerator
from scene_composer import SceneComposer
from scene_movement_analyzer import SceneMovementAnalyzer
from video_processor import VideoProcessor

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

progress = {"step": "Idle"}
story_text = ""

@app.route('/status', methods=['GET'])
def status():
    return jsonify(progress)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        return render_template('processing.html', title=title, description=description)
    return render_template('index.html')


def start_pipeline(story_text_local):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        final_path = loop.run_until_complete(run_pipeline(story_text_local))
    finally:
        loop.close()
    # After completion
    progress["step"] = "Complete"


@app.route('/generate', methods=['POST'])
def generate():
    title = request.form['title']
    description = request.form['description']
    global story_text
    story_text = f"{title}\n\n{description}"

    progress["step"] = "Starting..."
    t = threading.Thread(target=start_pipeline, args=(story_text,))
    t.start()

    return jsonify({"status": "started"})


async def run_pipeline(story_text_local):
    # Create fresh instances each run, ensuring a new run directory each time
    asset_manager = AssetManager()  # No run_dir passed, so a new run_* folder is created
    ai_manager = AIManager()
    story_analyzer = StoryAnalyzer()
    asset_generator = AssetGenerator(run_dir=asset_manager.run_dir)
    movement_analyzer = SceneMovementAnalyzer()
    scene_composer = SceneComposer(asset_manager)
    video_processor = VideoProcessor(asset_manager)

    progress["step"] = "Analyzing story..."
    story_data = await story_analyzer.analyze(story_text_local)

    # Ensure metadata directory is created
    story_data_path = asset_manager.get_path("metadata", "story_data.json")
    story_data_path.parent.mkdir(parents=True, exist_ok=True)

    with open(story_data_path, 'w') as f:
        json.dump(story_data, f, indent=2)
    logger.info(f"Saved story_data to {story_data_path}")

    progress["step"] = "Generating assets..."
    assets = await asset_generator.generate_all_assets(story_data)

    # Update each scene's background_path in story_data based on generated assets
    backgrounds_by_scene = {}
    for bg in assets["backgrounds"]:
        if "scene_id" in bg and "file_path" in bg:
            backgrounds_by_scene[bg["scene_id"]] = bg["file_path"]

    for scene in story_data["scenes"]:
        sid = scene["scene_id"]
        if sid in backgrounds_by_scene:
            scene["background_path"] = backgrounds_by_scene[sid]
        else:
            # fallback if not found
            scene["background_path"] = f"scene_{sid}_background.png"

    progress["step"] = "Analyzing scene movements..."
    scene_timelines = []
    for scene in story_data["scenes"]:
        timeline = movement_analyzer.analyze_scene(scene, story_data["characters"])
        scene_timelines.append(timeline)

    progress["step"] = "Composing scenes..."
    scenes = await scene_composer.compose_scenes(story_data, assets, scene_timelines)

    progress["step"] = "Creating final video for first scene..."
    if scenes:
        final_scene = scenes[0]
        # scene_composer.create_scene_video should now save the video in run_dir/scenes/video
        final_video_path = await scene_composer.create_scene_video(final_scene)
        progress["step"] = "Complete"
        return final_video_path
    else:
        progress["step"] = "Complete"
        return None

@app.route('/download')
def download():
    # Instead of a fixed path, we could track final_path if needed.
    # For simplicity, we'll just say if there's a known final video, return it.
    # If we rely on a known filename, adapt accordingly.
    # Example: If the first scene video is always scene_0.mp4 in run_dir/scenes/video,
    # we can try to find it in the last run_dir.

    # NOTE: This code might need to find the latest run directory and video file.
    # For demonstration, let's assume we know the last run and scene_0.mp4 is there.
    # A robust solution would track final_path from run_pipeline and store it somewhere.

    # If we want to just check the last run, we could do this (not required):
    # This is just placeholder logic. Adjust as needed.
    output_dir = Path("output")
    runs = sorted(output_dir.glob("run_*"))
    if not runs:
        return "No run found", 404
    last_run = runs[-1]
    video_path = last_run / "scenes" / "video" / "scene_0.mp4"
    if video_path.exists():
        return send_file(str(video_path), as_attachment=True)
    return "No video found", 404
