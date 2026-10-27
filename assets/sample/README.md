# TrendForge sample video

`trendforge-free-demo.mp4` is built by GitHub Actions using a no-paid-API workflow:

- Python and Pillow for original 9:16 motion-graphic scene cards
- FFmpeg for H.264/AAC encoding and styled captions
- Piper TTS with the `en_US-lessac-medium` model for local neural narration when the public model can be fetched
- Offline eSpeak NG as a reliable zero-cost fallback if Piper's model download is temporarily rate-limited
- Groq and YouTube APIs are **not** called for this fixture; no API secrets are needed

The Piper voice model is published under MIT on the public `rhasspy/piper-voices` Hugging Face repository. Its model weights are downloaded to the runner cache and are not copied into this Git repository.

The sample uses a locally authored illustrative script and is not a live YouTube trend report. Production uses Groq for script generation and the YouTube Data API for discovery/uploads, with the user's own free-tier credentials.
