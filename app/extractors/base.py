"""Platform detection: decides whether a URL is a video or a website."""
import re

VIDEO_PATTERNS = [
    r"youtube\.com/watch",
    r"youtube\.com/shorts/",
    r"youtube\.com/live/",
    r"youtu\.be/",
    r"tiktok\.com/",
    r"instagram\.com/reel",
    r"instagram\.com/p/",
    r"vimeo\.com/",
    r"twitch\.tv/",
    r"twitter\.com/.+/status",
    r"x\.com/.+/status",
    r"facebook\.com/.*video",
    r"reddit\.com/r/.*/comments",  # reddit video posts
]

_VIDEO_RE = re.compile("|".join(VIDEO_PATTERNS), re.IGNORECASE)


def is_video_url(url: str) -> bool:
    return bool(_VIDEO_RE.search(url))
