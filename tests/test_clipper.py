import pytest

from trendforge.clipper import (
    ClipCandidate, ClipError, TranscriptSegment, _select_non_overlapping,
    _validate_public_https_url, build_candidates,
)


def test_youtube_watch_urls_are_not_direct_source_downloads():
    with pytest.raises(ClipError, match="not a source file"):
        _validate_public_https_url("https://www.youtube.com/watch?v=abcdefghijk")
    with pytest.raises(ClipError, match="not a source file"):
        _validate_public_https_url("https://r2---sn.googlevideo.com/videoplayback?x=1")


def test_rejects_non_https_and_private_hosts():
    with pytest.raises(ClipError):
        _validate_public_https_url("http://example.com/video.mp4")
    with pytest.raises(ClipError, match="Private/local"):
        _validate_public_https_url("https://localhost/video.mp4")


def test_build_candidates_scores_transcript_hooks_and_scene_activity():
    segments = [
        TranscriptSegment(0, 7, "Today we are checking the ordinary part."),
        TranscriptSegment(12, 18, "Wait, this is actually insane! I never expected that."),
        TranscriptSegment(18, 27, "The trick finally works, but there is one surprising problem."),
        TranscriptSegment(28, 40, "Here is the result and why it matters."),
    ]
    candidates = build_candidates(60, 20, segments, [12, 15, 18, 24, 28, 33])
    assert candidates
    assert max(c.score for c in candidates) > 0
    assert any("insane" in c.transcript.lower() for c in candidates)


def test_non_overlapping_selection_picks_distinct_windows():
    candidates = [
        ClipCandidate(10, 40, .9, "best", 5),
        ClipCandidate(12, 42, .8, "overlap", 4),
        ClipCandidate(60, 90, .7, "second", 3),
    ]
    selected = _select_non_overlapping(candidates, 2)
    assert len(selected) == 2
    assert selected[0].end < selected[1].start
