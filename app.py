from flask import Flask, render_template, request, jsonify, send_file
import asyncio
import os
import threading
from pathlib import Path
import json
import logging
import subprocess

from asset_manager import AssetManager
from ai_manager import AIManager
from story_analyzer import StoryAnalyzer
from asset_generator import AssetGenerator
from scene_composer import SceneComposer
from scene_movement_analyzer import SceneMovementAnalyzer
from video_processor import VideoProcessor
from narration_generator import NarrationGenerator  # Assuming you have this implemented

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
        if final_path:
            logger.info(f"Pipeline complete. Final video: {final_path}")
        else:
            logger.info("Pipeline complete with no final video generated.")
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
    asset_manager = AssetManager()
    ai_manager = AIManager()
    story_analyzer = StoryAnalyzer()
    asset_generator = AssetGenerator(asset_manager=asset_manager)
    movement_analyzer = SceneMovementAnalyzer()
    scene_composer = SceneComposer(asset_manager)
    video_processor = VideoProcessor(asset_manager)
    narration_gen = NarrationGenerator(asset_manager=asset_manager)

    progress["step"] = "Analyzing story..."
    story_data = await story_analyzer.analyze(story_text_local)

    story_data_path = asset_manager.get_path("metadata", "story_data.json")
    story_data_path.parent.mkdir(parents=True, exist_ok=True)
    with open(story_data_path, 'w') as f:
        json.dump(story_data, f, indent=2)
    logger.info(f"Saved story_data to {story_data_path}")

    progress["step"] = "Generating assets..."
    assets = await asset_generator.generate_all_assets(story_data)

    # Generate narration audio for each scene
    progress["step"] = "Generating narration..."
    for scene in story_data["scenes"]:
        scene_id = scene["scene_id"]
        narration_text = scene.get("narration_text", "")
        audio_path, audio_duration = narration_gen.generate_narration_for_scene(scene_id, narration_text)
        scene["audio_path"] = str(audio_path)
        scene["audio_duration"] = audio_duration

    # Update backgrounds
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
        timeline = movement_analyzer.analyze_scene(scene, story_data["characters"], scene["audio_duration"])
        scene_timelines.append(timeline)

    progress["step"] = "Composing scenes..."
    scenes = await scene_composer.compose_scenes(story_data, assets, scene_timelines)

    # Generate videos for all scenes
    video_paths = []
    for idx, scene_data in enumerate(scenes):
        progress["step"] = f"Creating final video for scene {scene_data['scene_id']}..."
        video_path = await scene_composer.create_scene_video(scene_data)
        video_paths.append(video_path)
        logger.info(f"Video for scene {scene_data['scene_id']} created at {video_path}")

    # Combine each video with its audio
    progress["step"] = "Combining video with audio..."
    video_with_sound_paths = []
    for idx, scene_data in enumerate(scenes):
        scene_id = scene_data["scene_id"]
        audio_path = scene_data.get("audio_path")
        input_video = video_paths[idx]

        if audio_path and Path(audio_path).exists():
            output_with_sound = asset_manager.get_path("scenes/video_with_sound", f"scene_{scene_id}.mp4")
            output_with_sound.parent.mkdir(parents=True, exist_ok=True)

            cmd = [
                'ffmpeg', '-y',
                '-i', str(input_video),
                '-i', str(audio_path),
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-shortest',
                str(output_with_sound)
            ]
            logger.info(f"Combining video and audio for scene {scene_id}: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg error for scene {scene_id}: {result.stderr}")
            else:
                logger.info(f"Combined video with sound at: {output_with_sound}")
                video_with_sound_paths.append(output_with_sound)
        else:
            logger.warning(f"No audio found for scene {scene_id}, skipping audio merge.")
            # Could just append the silent video if desired

    # Now stitch all scenes together into one final video
    if video_with_sound_paths:
        progress["step"] = "Stitching all scenes into one final video..."
        final_video_dir = asset_manager.get_path("final_video", "")
        final_video_dir.mkdir(parents=True, exist_ok=True)

        final_video_path = asset_manager.get_path("final_video", "final_video.mp4")

        # Create a temporary file with list of input videos
        concat_list_path = final_video_dir / "concat_list.txt"
        with open(concat_list_path, 'w') as f:
            for v in video_with_sound_paths:
                # ffmpeg concat protocol requires paths in a certain format
                f.write(f"file '{v}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(concat_list_path),
            '-c', 'copy',
            str(final_video_path)
        ]
        logger.info(f"Stitching all scenes: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to stitch videos: {result.stderr}")
            final_video_path = None
        else:
            logger.info(f"Final stitched video at: {final_video_path}")
    else:
        final_video_path = None
        logger.warning("No video_with_sound files found to stitch into final video.")

    progress["step"] = "Complete"

    return str(final_video_path) if final_video_path and final_video_path.exists() else None

@app.route('/download')
def download():
    # Try to serve the final video if it exists
    # We'll assume the last generated run is the one to download from
    # You might store run_id in a session or a database and fetch it
    # For now, just pick the latest run directory
    runs = sorted(Path("output").glob("run_*"))
    if not runs:
        return "No run found", 404
    last_run = runs[-1]
    final_video_path = last_run / "final_video" / "final_video.mp4"
    if final_video_path.exists():
        return send_file(str(final_video_path), as_attachment=True)
    return "No final video found", 404
