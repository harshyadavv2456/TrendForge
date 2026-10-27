# TrendForge

**TrendForge can clip actual scenes from rights-cleared source footage into vertical Shorts.** The real-footage clipper finds candidate moments using scene changes and transcript signals, optionally ranks them with Groq, then cuts the original frames/audio, reframes to 9:16, adds captions, and retains source attribution.

## Run the real-footage clipper

1. Open Actions → TrendForge Real-Footage Clipper → Run workflow on main.
2. Supply a direct HTTPS media-file URL from the footage owner, a canonical source page URL, the title and creator name.
3. Confirm you have permission or a license allowing the edits and intended publication.
4. Leave Publish unchecked to create an artifact first. Review the clips, then run again with publishing enabled only when rights and OAuth setup are verified.
5. Download clip-01.mp4, clip-02.mp4, etc. from the workflow artifact.

**Important:** a YouTube watch URL is not a video-file URL. YouTube's Data API does not expose arbitrary source video downloads. For your own channel, download your original file from YouTube Studio; for someone else's channel, request a creator-provided master/download or explicit permission and a compliant source file. TrendForge intentionally does not scrape or bypass YouTube download restrictions. The video can be a genuine creator clip only when actual source footage is supplied.

The clipper can use Groq's free-tier transcription and text model for transcript-aware candidate ranking and captions. Without GROQ_API_KEY, it still clips real footage using local scene-cut heuristics, but output selection and captions are less intelligent. API limits and availability vary by account.

## Existing original-graphics pipeline

The earlier original-commentary/motion-graphics workflow remains available for manual preview only; its automatic schedule has been disabled so it will not continue posting the wrong format. It is separate from the real-footage clipper.

## Setup and safety

- For optional transcript ranking, configure GROQ_API_KEY under repository Settings → Secrets and variables → Actions.
- To publish from the clip workflow, configure YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN. The clip workflow defaults to preview artifact-only. Public publishing requires explicitly checking Publish.
- The rights checkbox is a self-attestation, not independent verification. Source permissions must cover the actual video, music, people/performances and the intended use. Reused-content monetization is not guaranteed.
- See docs/CLIPPER.md, docs/SETUP.md, docs/CONTENT_POLICY.md, and SECURITY.md.

## Local development

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-clipper.txt
    pytest -q tests/test_clipper.py
    python -m trendforge.clipper --input ./source-video.mp4 \
      --source-url "https://www.youtube.com/watch?v=YOUR_SOURCE_ID" \
      --title "Source title" --creator "Source creator" --rights-confirmed
