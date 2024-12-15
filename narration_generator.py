import os
import logging
from pathlib import Path
from elevenlabs.client import ElevenLabs
from pydub import AudioSegment

logger = logging.getLogger(__name__)

class NarrationGenerator:
    def __init__(self, asset_manager, voice_id="Tbu7gkp47JsKjHLbGbtC", model="eleven_multilingual_v2"):
        self.asset_manager = asset_manager
        elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
        if not elevenlabs_api_key:
            raise ValueError("ELEVENLABS_API_KEY not set in environment variables.")
        self.client = ElevenLabs(api_key=elevenlabs_api_key)
        self.voice_id = voice_id
        self.model = model

    def generate_narration_for_scene(self, scene_id: int, narration_text: str) -> (Path, float):
        """
        Generate an audio file from narration_text using ElevenLabs TTS.
        Save as scene_{scene_id}.mp3 in scenes/audio/.
        Return audio_path and duration (in seconds).
        """
        # Ensure scenes/audio directory
        audio_dir = self.asset_manager.get_path("scenes", "audio")
        audio_dir.mkdir(parents=True, exist_ok=True)

        audio_filename = f"scene_{scene_id}.mp3"
        audio_path = audio_dir / audio_filename

        logger.info(f"Generating narration audio for scene {scene_id}...")
        self._generate_audio(narration_text, str(audio_path))
        logger.info(f"Saved narration audio to: {audio_path}")

        # Measure audio duration
        audio_segment = AudioSegment.from_file(str(audio_path))
        duration_seconds = len(audio_segment) / 1000.0
        logger.info(f"Audio duration for scene {scene_id}: {duration_seconds}s")

        return audio_path, duration_seconds

    def _generate_audio(self, text: str, output_filename: str):
        """
        Generate audio using ElevenLabs client and save to output_filename.
        """
        try:
            audio_generator = self.client.generate(
                text=text,
                voice=self.voice_id,
                model=self.model
            )

            with open(output_filename, "wb") as audio_file:
                for chunk in audio_generator:
                    audio_file.write(chunk)

        except Exception as e:
            logger.error(f"Error generating audio: {e}")
            raise

