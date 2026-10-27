# TrendForge sample video

`trendforge-free-demo.mp4` is built by GitHub Actions using a fully local, no-paid-API workflow:

- Python and Pillow for original 9:16 motion-graphic scene cards
- FFmpeg for H.264/AAC MP4 encoding and styled captions
- Piper TTS and the `en_US-lessac-medium` model for local neural narration
- Groq and YouTube APIs are **not** called for this fixture; no API secrets are needed

The Piper voice model is published under MIT on the public `rhasspy/piper-voices` Hugging Face repository. Its model weights are downloaded to the runner cache on the first run and are not copied into this Git repository.

The script and source context are illustrative. This is a sample of the rendered format, captions and local speech quality, not a live YouTube trend report. Production uses Groq for script generation and the YouTube Data API for discovery/uploads, both with the user's own free-tier credentials.
