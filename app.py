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
    # Create fresh instances for this run
    asset_manager = AssetManager()  # new run directory each time
    ai_manager = AIManager()
    story_analyzer = StoryAnalyzer()
    # Pass asset_manager directly to AssetGenerator
    asset_generator = AssetGenerator(asset_manager=asset_manager)
    movement_analyzer = SceneMovementAnalyzer()
    scene_composer = SceneComposer(asset_manager)
    video_processor = VideoProcessor(asset_manager)

    progress["step"] = "Analyzing story..."
    story_data = await story_analyzer.analyze(story_text_local)

    story_data_path = asset_manager.get_path("metadata", "story_data.json")
    story_data_path.parent.mkdir(parents=True, exist_ok=True)
    with open(story_data_path, 'w') as f:
        json.dump(story_data, f, indent=2)
    logger.info(f"Saved story_data to {story_data_path}")

    progress["step"] = "Generating assets..."
    assets = await asset_generator.generate_all_assets(story_data)

    backgrounds_by_scene = {}
    for bg in assets["backgrounds"]:
        if "scene_id" in bg and "file_path" in bg:
            backgrounds_by_scene[bg["scene_id"]] = bg["file_path"]

    for scene in story_data["scenes"]:
        sid = scene["scene_id"]
        if sid in backgrounds_by_scene:
            scene["background_path"] = backgrounds_by_scene[sid]
        else:
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
        final_video_path = await scene_composer.create_scene_video(final_scene)
        progress["step"] = "Complete"
        return final_video_path
    else:
        progress["step"] = "Complete"
        return None

@app.route('/download')
def download():
    # Since we create a new run each time, we should specify which run to download from
    # For simplicity, let's just try the last run or a known file
    # If you have logic to track final_video_path, use that.
    # Otherwise, adapt as needed.
    return "No video found", 404
