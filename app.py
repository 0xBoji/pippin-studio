from flask import Flask, render_template, request, jsonify, send_file
import asyncio
import os
import threading
from pathlib import Path
import json
import logging
import subprocess

from asset_manager import AssetManager
from story_analyzer import StoryAnalyzer
from asset_generator import AssetGenerator
from scene_composer import SceneComposer
from scene_movement_analyzer import SceneMovementAnalyzer
from video_processor import VideoProcessor
from narration_generator import NarrationGenerator  # Assuming implemented

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger("PIL").setLevel(logging.WARNING)

app = Flask(__name__)

progress = {"step": "Idle"}
story_text = ""
current_run_id = None

generation_mode = "prompt"
scene_count = "auto"

def get_runs():
    runs = sorted(Path("output").glob("run_*"))
    return runs

@app.route('/history', methods=['GET'])
def history():
    runs = get_runs()
    data = []
    for run_dir in runs:
        run_id = run_dir.name
        final_video = run_dir / "final_video" / "final_video.mp4"
        story_data = run_dir / "metadata" / "story_data.json"
        item = {
            "run_id": run_id,
            "final_video_exists": final_video.exists(),
            "final_video_path": str(final_video) if final_video.exists() else None,
            "story_data_exists": story_data.exists()
        }
        data.append(item)
    data.sort(key=lambda x: x["run_id"], reverse=True)
    return jsonify(data)

@app.route('/run_data/<run_id>', methods=['GET'])
def run_data(run_id):
    run_dir = Path("output") / run_id
    if not run_dir.exists():
        return jsonify({})

    story_data_path = run_dir / "metadata" / "story_data.json"
    story_data = {}
    if story_data_path.exists():
        with open(story_data_path, 'r') as f:
            story_data = json.load(f)

    scene_movements_path = run_dir / "metadata" / "scene_movements.json"
    scene_movements = []
    if scene_movements_path.exists():
        with open(scene_movements_path, 'r') as f:
            scene_movements = json.load(f)

    characters_dir = run_dir / "characters"
    animations_dir = run_dir / "animations"
    backgrounds_dir = run_dir / "backgrounds"
    scenes_dir = run_dir / "scenes"
    final_video_path = run_dir / "final_video" / "final_video.mp4"

    # Collect characters SVGs
    characters = []
    if characters_dir.exists():
        for svg in characters_dir.glob("*.svg"):
            characters.append(str(svg))

    # Collect animations
    animations = {}
    if animations_dir.exists():
        for anim_svg in animations_dir.glob("*.svg"):
            animations[anim_svg.stem] = str(anim_svg)

    # Scenes data
    scenes_data = []
    if scenes_dir.exists():
        video_with_sound_dir = scenes_dir / "video_with_sound"
        audio_dir = scenes_dir / "audio"
        svg_dir = scenes_dir / "svg"
        if video_with_sound_dir.exists():
            for video_file in video_with_sound_dir.glob("*.mp4"):
                sid = video_file.stem.replace("scene_","")
                scene_audio = audio_dir / f"scene_{sid}.mp3"
                scene_svg = svg_dir / f"scene_{sid}.svg"
                scenes_data.append({
                    "scene_id": sid,
                    "video": str(video_file) if video_file.exists() else None,
                    "audio": str(scene_audio) if scene_audio.exists() else None,
                    "svg": str(scene_svg) if scene_svg.exists() else None
                })

    data = {
        "run_id": run_id,
        "story_data": story_data,
        "scene_movements": scene_movements,
        "characters": characters,
        "animations": animations,
        "scenes": scenes_data,
        "final_video": str(final_video_path) if final_video_path.exists() else None
    }

    return jsonify(data)

@app.route('/status', methods=['GET'])
def status():
    return jsonify(progress)

@app.route('/file')
def serve_file():
    path = request.args.get('path')
    if not path:
        return "No path provided", 400
    full_path = Path(path)
    if not full_path.exists():
        return "File not found", 404
    return send_file(str(full_path))

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

def start_pipeline(story_text_local, generation_mode_local, scene_count_local):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        final_path = loop.run_until_complete(run_pipeline(story_text_local, generation_mode_local, scene_count_local))
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
    global story_text, generation_mode, scene_count
    generation_mode = request.form.get('generation_mode', 'prompt')
    scene_count = request.form.get('scene_count', 'auto')

    story_text = f"{title}\n\n{description}"

    progress["step"] = "Starting..."
    t = threading.Thread(target=start_pipeline, args=(story_text, generation_mode, scene_count))
    t.start()

    return jsonify({"status": "started"})

async def run_pipeline(story_text_local, generation_mode_local, scene_count_local):
    asset_manager = AssetManager()
    global current_run_id
    current_run_id = asset_manager.run_id

    story_analyzer = StoryAnalyzer(generation_mode=generation_mode_local, scene_count=scene_count_local)
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

    progress["step"] = "Generating narration..."
    for scene in story_data["scenes"]:
        scene_id = scene["scene_id"]
        narration_text = scene.get("narration_text", "")
        audio_path, audio_duration = narration_gen.generate_narration_for_scene(scene_id, narration_text)
        scene["audio_path"] = str(audio_path)
        scene["audio_duration"] = audio_duration

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

    video_paths = []
    for idx, scene_data in enumerate(scenes):
        progress["step"] = f"Creating final video for scene {scene_data['scene_id']}..."
        video_path = await scene_composer.create_scene_video(scene_data)
        video_paths.append(video_path)
        logger.info(f"Video for scene {scene_data['scene_id']} created at {video_path}")

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

    if video_with_sound_paths:
        progress["step"] = "Stitching all scenes into one final video..."
        final_video_dir = asset_manager.get_path("final_video", "")
        final_video_dir.mkdir(parents=True, exist_ok=True)

        final_video_path = asset_manager.get_path("final_video", "final_video.mp4")

        concat_list_path = final_video_dir / "concat_list.txt"
        with open(concat_list_path, 'w') as f:
            for v in video_with_sound_paths:
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

        # After final_video.mp4 is created, produce vertical and horizontal versions
        if final_video_path and final_video_path.exists():
            # final_video_vertical (9:16)
            # 1024x1024 -> crop to 576x1024 (centered horizontally)
            # crop=width:height:x:y = crop=576:1024:224:0
            final_video_vertical = final_video_dir / "final_video_vertical.mp4"
            cmd_vertical = [
                'ffmpeg', '-y',
                '-i', str(final_video_path),
                '-filter:v', 'crop=576:1024:224:0',
                '-c:a', 'copy',
                str(final_video_vertical)
            ]
            logger.info(f"Creating vertical video: {' '.join(cmd_vertical)}")
            subprocess.run(cmd_vertical, capture_output=True, text=True)

            # final_video_horizontal (16:9)
            # 1024x1024 -> crop to 1024x576 (centered vertically)
            # crop=1024:576:0:224
            final_video_horizontal = final_video_dir / "final_video_horizontal.mp4"
            cmd_horizontal = [
                'ffmpeg', '-y',
                '-i', str(final_video_path),
                '-filter:v', 'crop=1024:576:0:224',
                '-c:a', 'copy',
                str(final_video_horizontal)
            ]
            logger.info(f"Creating horizontal video: {' '.join(cmd_horizontal)}")
            subprocess.run(cmd_horizontal, capture_output=True, text=True)
    else:
        final_video_path = None
        logger.warning("No video_with_sound files found to stitch into final video.")

    progress["step"] = "Complete"
    return str(final_video_path) if final_video_path and final_video_path.exists() else None

@app.route('/download')
def download():
    runs = get_runs()
    if not runs:
        return "No run found", 404
    last_run = runs[-1]
    final_video_path = last_run / "final_video" / "final_video.mp4"
    if final_video_path.exists():
        return send_file(str(final_video_path), as_attachment=True)
    return "No final video found", 404
