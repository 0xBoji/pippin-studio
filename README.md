# Pippin Studio

Created by [@yoheinakajima](https://x.com/yoheinakajima) for the [@pippinlovesyou](https://x.com/pippinlovesyou) project, a continued exploration in AI-generated kids content, inspired by the early success of the Bedtime Stories with Pippin podcast. [Learn more](https://x.com/yoheinakajima/status/1871848832004145233).

---

# Storybook Video Generation Pipeline

Welcome! This project assembles a multi-step pipeline that takes in story text (or a prompt) and automatically produces a narrated, animated storybook video. It uses:

- **Flask** for the web interface (front-end)
- **OpenAI / DALL·E / ElevenLabs** for generating story text, images, voice narration, and animations
- **FFmpeg** and other libraries for compositing and encoding the final video

Below is a comprehensive guide on how to install, configure, and run this pipeline, both through a user-friendly web front-end and directly from back-end code.

---

## Table of Contents

1. Key Components & Flow
2. Prerequisites
3. Installation
4. Environment Variables
5. Running via Front-End (Flask App)
6. Running Directly Through Back-End
7. Included Generation Options
8. File/Directory Overview
9. Usage Tips & Troubleshooting

---

## Key Components & Flow

User provides a story prompt or a full story:

- **Prompt Mode**: The system will generate a full story with multiple scenes from the given title & description.
- **Full-Text Mode**: The provided text is treated as the complete story itself.

### Story Analysis (`story_analyzer.py`):
- Extracts scenes, characters, background descriptions, and other metadata.

### Asset Generation (`asset_generator.py`):
- Generates background images using DALL·E.
- Generates characters and animations (SVGs) using language-model prompts.

### Scene Movement Analysis (`scene_movement_analyzer.py`):
- Calculates how characters move and which animations to apply in each scene.

### Narration Generation (`narration_generator.py`):
- Creates voice-over audio for each scene (using ElevenLabs TTS).

### Scene Composition & Video Processing (`scene_composer.py` and `video_processor.py`):
- Creates scene SVGs, merges background + characters, applies movements/animations.
- Converts frames to video with FFmpeg and stitches all scenes into a final video.

### Output:
- Final MP4 video in various orientations (square, vertical, horizontal).
- All intermediate assets (SVGs, PNG backgrounds, audio, etc.) stored in an `output/run_<timestamp>_...` directory.

---

## Prerequisites

- **Python 3.8+**
- **FFmpeg** command-line tool (must be installed and available in your PATH).
- **Poetry** or **pip** for dependency management (choose one).
- **OpenAI account** (with API key) if you are using GPT models or DALL·E.
- **ElevenLabs account** (with API key) if you want text-to-speech narration.

---

## Installation

### Clone the repository:

```bash
git clone https://github.com/yoheinakajima/pippin-studio.git
cd pippin-studio
```

### Install dependencies:

#### Option A (Poetry):

```bash
poetry install
poetry shell
```

#### Option B (pip):

```bash
pip install -r requirements.txt
```

### Confirm FFmpeg is installed:

```bash
ffmpeg -version
```

You should see version information. If not, please install FFmpeg.

---

## Environment Variables

Set the following environment variables as needed:

- `OPENAI_API_KEY`: Required for OpenAI GPT and DALL·E calls.
- `ELEVENLABS_API_KEY`: Required for ElevenLabs text-to-speech.
- `PYTHONUNBUFFERED=1` (recommended) to see logs in real time.

You can export them in your terminal:

```bash
export OPENAI_API_KEY="sk-..."
export ELEVENLABS_API_KEY="..."
```

Or store them in a `.env` file (if you’re using something like dotenv or your own approach).

---

## Running via Front-End (Flask App)

### Start the Flask Server:

```bash
python main.py
```

By default, it listens at `http://0.0.0.0:8080`.

### Open the Browser Interface:

Navigate to `http://localhost:8080` (or your server IP if deploying remotely). You’ll see a form where you can enter:

- **Story Title**
- **Story Prompt or Full Story Text**
- **Generation Mode** (prompt vs. full_text)
- **Number of Scenes** (or "auto")

Then click **Generate Story**.

### Status & Progress:

The interface periodically polls `/status` to show pipeline progress (e.g., "Analyzing story…", "Generating assets…", etc.). Once complete, a **Download Final Video** link will appear.

### History & Run Details:

The left pane lists all previous runs by `run_id`. Clicking a run shows details:
- Scenes, background images, character SVGs, animations, final videos.
- You can re-download or re-inspect any run’s output.

---

## Running Directly Through Back-End

You may want to run the pipeline without the Flask front-end (e.g., from a script or in a notebook). The main pipeline entry point is the `run_pipeline` function in `app.py`:

### Import & call `run_pipeline`:

```python
import asyncio
from app import run_pipeline

story_text = "My Awesome Story Title\n\nDetailed story prompt or text here..."
generation_mode = "prompt"  # or "full_text"
scene_count = "auto"        # or "5" or any integer as a string

async def main():
    final_video_path = await run_pipeline(story_text, generation_mode, scene_count)
    print(f"Done! Final video at: {final_video_path}")

asyncio.run(main())
```

---

## Included Generation Options

- **Generation Mode (`generation_mode`)**:
  - `prompt`: Interprets the provided text as a prompt, then automatically composes a full story before extracting scenes.
  - `full_text`: Takes the provided text verbatim as the story, then extracts scenes directly.
- **Scene Count (`scene_count`)**:
  - `auto`: Let the pipeline decide a natural number of scenes based on the story.
  - A numeric string (e.g., "4"): Force exactly that many scenes.
- **Additional Steps**:
  - Narration: Uses ElevenLabs TTS to generate per-scene narration.
  - Vertical & Horizontal Crops: Produces `final_video_vertical.mp4` (9:16) and `final_video_horizontal.mp4` (16:9).

---

## File/Directory Overview

### Main Files
- **`main.py`**: Simple entry point. Runs the Flask app on `0.0.0.0:8080`.
- **`app.py`**: The primary Flask routes and `run_pipeline` logic.
- **Modules**:
  - `asset_generator.py`: Generates backgrounds via DALL·E; creates character/animation SVGs from LLM prompts.
  - `story_analyzer.py`: Analyzes and extracts story components.
  - `video_processor.py`: Renders frames (with animations) and encodes MP4s.

---

## Usage Tips & Troubleshooting

- **Long Scenes / Slow Generation**: Generating many scenes or large images can be time-intensive. Check your API usage limits.
- **Missing or Invalid Keys**: Ensure `OPENAI_API_KEY` and `ELEVENLABS_API_KEY` are set.
- **FFmpeg Not Found**: Make sure FFmpeg is installed system-wide.
- **Customizing**: You can tweak many aspects by editing the relevant Python modules.

Enjoy creating storybook-style videos with automatically generated characters, backgrounds, and narration! If you find issues or have ideas for improvements, feel free to submit an issue or pull request. Happy storytelling!
