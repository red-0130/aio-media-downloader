"""Canned metadata fixtures representing all media types across platforms."""

from typing import Any

# ============================================================================
# YouTube Canned Payloads (yt-dlp JSON)
# ============================================================================

MOCK_YOUTUBE_VIDEO: dict[str, Any] = {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
    "uploader": "Rick Astley",
    "channel": "Rick Astley",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "duration": 212.0,
    "ext": "mp4",
    "vcodec": "avc1.64001f",
    "acodec": "mp4a.40.2",
    "filesize": 34812900,
    "height": 1080,
    "width": 1920,
    "formats": [
        {
            "format_id": "18",
            "ext": "mp4",
            "height": 360,
            "width": 640,
            "vcodec": "avc1.42001E",
            "acodec": "mp4a.40.2",
            "filesize": 12053891,
        },
        {
            "format_id": "22",
            "ext": "mp4",
            "height": 720,
            "width": 1280,
            "vcodec": "avc1.64001F",
            "acodec": "mp4a.40.2",
            "filesize": 25489100,
        },
        {
            "format_id": "137",
            "ext": "mp4",
            "height": 1080,
            "width": 1920,
            "vcodec": "avc1.64001F",
            "acodec": "none",
            "filesize": 34812900,
        },
    ],
}

MOCK_YOUTUBE_SHORT: dict[str, Any] = {
    "id": "short_12345678",
    "title": "Amazing Skateboarding Trick #Shorts",
    "uploader": "SkateDaily",
    "channel": "SkateDaily",
    "thumbnail": "https://i.ytimg.com/vi/short_12345678/frame.jpg",
    "duration": 28.0,
    "ext": "mp4",
    "vcodec": "avc1.64001f",
    "acodec": "mp4a.40.2",
    "filesize": 8900000,
    "height": 1920,
    "width": 1080,
    "formats": [
        {
            "format_id": "short_1080",
            "ext": "mp4",
            "height": 1920,
            "width": 1080,
            "vcodec": "avc1.64001F",
            "acodec": "mp4a.40.2",
            "filesize": 8900000,
        }
    ],
}

MOCK_YOUTUBE_PLAYLIST: dict[str, Any] = {
    "id": "PL_sample_playlist",
    "title": "Top Hits 2024 Playlist",
    "uploader": "MusicArchive",
    "channel": "MusicArchive",
    "thumbnail": "https://i.ytimg.com/vi/playlist_thumb.jpg",
    "entries": [
        {
            "id": "pl_item_1",
            "title": "Summer Song 1",
            "url": "https://www.youtube.com/watch?v=pl_item_1",
            "webpage_url": "https://www.youtube.com/watch?v=pl_item_1",
            "thumbnail": "https://i.ytimg.com/vi/pl_item_1/thumb.jpg",
            "duration": 180,
            "width": 1920,
            "height": 1080,
            "vcodec": "h264",
        },
        {
            "id": "pl_item_2",
            "title": "Summer Song 2",
            "url": "https://www.youtube.com/watch?v=pl_item_2",
            "webpage_url": "https://www.youtube.com/watch?v=pl_item_2",
            "thumbnail": "https://i.ytimg.com/vi/pl_item_2/thumb.jpg",
            "duration": 205,
            "width": 1920,
            "height": 1080,
            "vcodec": "h264",
        },
        {
            "id": "pl_item_3",
            "title": "Summer Song 3",
            "url": "https://www.youtube.com/watch?v=pl_item_3",
            "webpage_url": "https://www.youtube.com/watch?v=pl_item_3",
            "thumbnail": "https://i.ytimg.com/vi/pl_item_3/thumb.jpg",
            "duration": 195,
            "width": 1920,
            "height": 1080,
            "vcodec": "h264",
        },
    ],
}

MOCK_YOUTUBE_AUDIO: dict[str, Any] = {
    "id": "audio_track_99",
    "title": "Lofi Chill Beats to Relax To",
    "uploader": "LofiStream",
    "thumbnail": "https://i.ytimg.com/vi/audio_track_99/thumb.jpg",
    "duration": 300.0,
    "ext": "mp3",
    "vcodec": "none",
    "acodec": "mp3",
    "filesize": 7200000,
    "formats": [
        {
            "format_id": "audio_only",
            "ext": "mp3",
            "vcodec": "none",
            "acodec": "mp3",
            "filesize": 7200000,
        }
    ],
}

# ============================================================================
# Instagram Canned Payloads
# ============================================================================

MOCK_INSTAGRAM_REEL: dict[str, Any] = {
    "id": "C7Reel12345",
    "title": "Funny dog jumps over puddle",
    "uploader": "doggo_world",
    "channel": "doggo_world",
    "thumbnail": "https://instagram.com/reel/C7Reel12345/thumb.jpg",
    "duration": 18.0,
    "ext": "mp4",
    "vcodec": "h264",
    "acodec": "aac",
    "filesize": 5120000,
    "height": 1920,
    "width": 1080,
    "formats": [
        {
            "format_id": "best",
            "ext": "mp4",
            "height": 1920,
            "width": 1080,
            "vcodec": "h264",
            "acodec": "aac",
            "filesize": 5120000,
        }
    ],
}

MOCK_INSTAGRAM_POST: list[dict[str, Any]] = [
    {
        "post_id": "post_photo_1001",
        "user": "nature_lens",
        "description": "Misty morning in the Pacific Northwest 🌲",
        "extension": "jpg",
        "url": "https://instagram.com/p/post_photo_1001/1.jpg",
        "thumbnail": "https://instagram.com/p/post_photo_1001/1_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-10 09:00:00",
    }
]

MOCK_INSTAGRAM_CAROUSEL: list[dict[str, Any]] = [
    {
        "post_id": "334819201948",
        "user": "photography_club",
        "description": "Golden hour in the city 🌆✨",
        "extension": "jpg",
        "url": "https://instagram.com/p/334819201948/1.jpg",
        "thumbnail": "https://instagram.com/p/334819201948/1_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-12 18:30:00",
    },
    {
        "post_id": "334819201948",
        "user": "photography_club",
        "description": "Golden hour in the city 🌆✨",
        "extension": "jpg",
        "url": "https://instagram.com/p/334819201948/2.jpg",
        "thumbnail": "https://instagram.com/p/334819201948/2_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-12 18:30:00",
    },
    {
        "post_id": "334819201948",
        "user": "photography_club",
        "description": "Golden hour in the city 🌆✨",
        "extension": "mp4",
        "url": "https://instagram.com/p/334819201948/3.mp4",
        "thumbnail": "https://instagram.com/p/334819201948/3_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "duration": 12.0,
        "date": "2024-05-12 18:30:00",
    },
]

MOCK_INSTAGRAM_STORY: list[dict[str, Any]] = [
    {
        "post_id": "story_94821038",
        "user": "influencer_daily",
        "description": "Good morning coffee vibe ☕️",
        "extension": "jpg",
        "url": "https://instagram.com/stories/influencer_daily/94821038_1.jpg",
        "thumbnail": "https://instagram.com/stories/influencer_daily/94821038_1_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "date": "2024-05-15 08:15:00",
    },
    {
        "post_id": "story_94821039",
        "user": "influencer_daily",
        "description": "Quick morning workout video",
        "extension": "mp4",
        "url": "https://instagram.com/stories/influencer_daily/94821039_2.mp4",
        "thumbnail": "https://instagram.com/stories/influencer_daily/94821039_2_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "duration": 15.0,
        "date": "2024-05-15 08:30:00",
    },
]

MOCK_INSTAGRAM_STORY_4_ITEMS: list[dict[str, Any]] = [
    {
        "post_id": "story_slide_1",
        "user": "influencer_daily",
        "description": "Good morning coffee vibe ☕️",
        "extension": "jpg",
        "url": "https://instagram.com/stories/influencer_daily/story_slide_1.jpg",
        "thumbnail": "https://instagram.com/stories/influencer_daily/story_slide_1_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "date": "2024-05-15 08:15:00",
        "original_name_first": "coffee_morning",
    },
    {
        "post_id": "story_slide_2",
        "user": "influencer_daily",
        "description": "OOTD outfit check 👗",
        "extension": "jpg",
        "url": "https://instagram.com/stories/influencer_daily/story_slide_2.jpg",
        "thumbnail": "https://instagram.com/stories/influencer_daily/story_slide_2_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "date": "2024-05-15 08:20:00",
        "original_name_first": "outfit_check",
    },
    {
        "post_id": "story_clip_3",
        "user": "influencer_daily",
        "description": "Quick morning workout video",
        "extension": "mp4",
        "url": "https://instagram.com/stories/influencer_daily/story_clip_3.mp4",
        "thumbnail": "https://instagram.com/stories/influencer_daily/story_clip_3_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "duration": 15.0,
        "date": "2024-05-15 08:30:00",
        "original_name_first": "morning_workout",
    },
    {
        "post_id": "story_clip_4",
        "user": "influencer_daily",
        "description": "Smoothie recipe clip 🍓",
        "extension": "mp4",
        "url": "https://instagram.com/stories/influencer_daily/story_clip_4.mp4",
        "thumbnail": "https://instagram.com/stories/influencer_daily/story_clip_4_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "duration": 12.0,
        "date": "2024-05-15 08:45:00",
        "original_name_first": "smoothie_recipe",
    },
]

MOCK_INSTAGRAM_CAROUSEL_5: list[dict[str, Any]] = [
    {
        "post_id": "item_0",
        "user": "photography_club",
        "description": "Photo 0",
        "extension": "jpg",
        "url": "https://instagram.com/p/carousel_5/0.jpg",
        "thumbnail": "https://instagram.com/p/carousel_5/0_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-12 18:30:00",
    },
    {
        "post_id": "item_1",
        "user": "photography_club",
        "description": "Photo 1",
        "extension": "jpg",
        "url": "https://instagram.com/p/carousel_5/1.jpg",
        "thumbnail": "https://instagram.com/p/carousel_5/1_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-12 18:30:00",
    },
    {
        "post_id": "item_2",
        "user": "photography_club",
        "description": "Photo 2",
        "extension": "jpg",
        "url": "https://instagram.com/p/carousel_5/2.jpg",
        "thumbnail": "https://instagram.com/p/carousel_5/2_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-12 18:30:00",
    },
    {
        "post_id": "item_3",
        "user": "photography_club",
        "description": "Photo 3",
        "extension": "jpg",
        "url": "https://instagram.com/p/carousel_5/3.jpg",
        "thumbnail": "https://instagram.com/p/carousel_5/3_thumb.jpg",
        "width": 1080,
        "height": 1350,
        "date": "2024-05-12 18:30:00",
    },
    {
        "post_id": "item_4",
        "user": "photography_club",
        "description": "Video 4",
        "extension": "mp4",
        "url": "https://instagram.com/p/carousel_5/4.mp4",
        "thumbnail": "https://instagram.com/p/carousel_5/4_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "duration": 12.0,
        "date": "2024-05-12 18:30:00",
    },
]

# ============================================================================
# Twitter / X Canned Payloads
# ============================================================================

MOCK_TWITTER_VIDEO: dict[str, Any] = {
    "id": "1789012345678901234",
    "title": "Rocket launch captured in 4K from tracking station",
    "uploader": "SpaceFlightNow",
    "channel": "SpaceFlightNow",
    "thumbnail": "https://pbs.twimg.com/media/rocket_thumb.jpg",
    "duration": 42.0,
    "ext": "mp4",
    "vcodec": "h264",
    "acodec": "aac",
    "filesize": 18400000,
    "height": 1080,
    "width": 1920,
    "formats": [
        {
            "format_id": "http-1080p",
            "ext": "mp4",
            "height": 1080,
            "width": 1920,
            "vcodec": "h264",
            "acodec": "aac",
            "filesize": 18400000,
        },
        {
            "format_id": "http-720p",
            "ext": "mp4",
            "height": 720,
            "width": 1280,
            "vcodec": "h264",
            "acodec": "aac",
            "filesize": 9200000,
        },
    ],
}

MOCK_TWITTER_GALLERY: list[dict[str, Any]] = [
    {
        "tweet_id": "1789098765432109876",
        "author": "digital_artist",
        "description": "Character concepts for my upcoming comic project!",
        "extension": "jpg",
        "url": "https://pbs.twimg.com/media/art_concept_1.jpg",
        "thumbnail": "https://pbs.twimg.com/media/art_concept_1_thumb.jpg",
        "width": 2048,
        "height": 1536,
        "date": "2024-05-14 14:00:00",
    },
    {
        "tweet_id": "1789098765432109876",
        "author": "digital_artist",
        "description": "Character concepts for my upcoming comic project!",
        "extension": "jpg",
        "url": "https://pbs.twimg.com/media/art_concept_2.jpg",
        "thumbnail": "https://pbs.twimg.com/media/art_concept_2_thumb.jpg",
        "width": 2048,
        "height": 1536,
        "date": "2024-05-14 14:00:00",
    },
    {
        "tweet_id": "1789098765432109876",
        "author": "digital_artist",
        "description": "Character concepts for my upcoming comic project!",
        "extension": "jpg",
        "url": "https://pbs.twimg.com/media/art_concept_3.jpg",
        "thumbnail": "https://pbs.twimg.com/media/art_concept_3_thumb.jpg",
        "width": 2048,
        "height": 1536,
        "date": "2024-05-14 14:00:00",
    },
    {
        "tweet_id": "1789098765432109876",
        "author": "digital_artist",
        "description": "Character concepts for my upcoming comic project!",
        "extension": "jpg",
        "url": "https://pbs.twimg.com/media/art_concept_4.jpg",
        "thumbnail": "https://pbs.twimg.com/media/art_concept_4_thumb.jpg",
        "width": 2048,
        "height": 1536,
        "date": "2024-05-14 14:00:00",
    },
]

# ============================================================================
# TikTok Canned Payloads
# ============================================================================

MOCK_TIKTOK_VIDEO: dict[str, Any] = {
    "id": "7369123456789012345",
    "title": "Cooking the best carbonara in under 15 minutes! 🍝",
    "uploader": "cheftips_official",
    "channel": "cheftips_official",
    "thumbnail": "https://p16-sign.tiktokcdn.com/carbonara_thumb.jpg",
    "duration": 58.0,
    "ext": "mp4",
    "vcodec": "h264",
    "acodec": "aac",
    "filesize": 14200000,
    "height": 1920,
    "width": 1080,
    "formats": [
        {
            "format_id": "download_addr",
            "ext": "mp4",
            "height": 1920,
            "width": 1080,
            "vcodec": "h264",
            "acodec": "aac",
            "filesize": 14200000,
        }
    ],
}

MOCK_TIKTOK_SLIDESHOW: list[dict[str, Any]] = [
    {
        "id": "7369999888777666555_1",
        "user": "travel_couple",
        "description": "Hidden gems in Kyoto that tourist guides miss 🌸",
        "extension": "jpg",
        "url": "https://p16-sign.tiktokcdn.com/slide_1.jpg",
        "thumbnail": "https://p16-sign.tiktokcdn.com/slide_1_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "date": "2024-05-11 12:00:00",
    },
    {
        "id": "7369999888777666555_2",
        "user": "travel_couple",
        "description": "Hidden gems in Kyoto that tourist guides miss 🌸",
        "extension": "jpg",
        "url": "https://p16-sign.tiktokcdn.com/slide_2.jpg",
        "thumbnail": "https://p16-sign.tiktokcdn.com/slide_2_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "date": "2024-05-11 12:00:00",
    },
    {
        "id": "7369999888777666555_3",
        "user": "travel_couple",
        "description": "Hidden gems in Kyoto that tourist guides miss 🌸",
        "extension": "jpg",
        "url": "https://p16-sign.tiktokcdn.com/slide_3.jpg",
        "thumbnail": "https://p16-sign.tiktokcdn.com/slide_3_thumb.jpg",
        "width": 1080,
        "height": 1920,
        "date": "2024-05-11 12:00:00",
    },
]


def resolve_ytdlp_metadata(url: str) -> dict[str, Any]:
    """Resolve mock yt-dlp metadata for given URL."""
    u = url.lower()
    if "short" in u:
        return MOCK_YOUTUBE_SHORT
    elif "playlist" in u:
        return MOCK_YOUTUBE_PLAYLIST
    elif "audio" in u:
        return MOCK_YOUTUBE_AUDIO
    elif "instagram.com" in u and ("reel" in u or "tv" in u):
        return MOCK_INSTAGRAM_REEL
    elif "twitter.com" in u or "x.com" in u:
        return MOCK_TWITTER_VIDEO
    elif "tiktok.com" in u:
        return MOCK_TIKTOK_VIDEO
    # Generic or standard YouTube
    return MOCK_YOUTUBE_VIDEO


def resolve_gallerydl_metadata(url: str) -> list[dict[str, Any]]:
    """Resolve mock gallery-dl metadata list for given URL."""
    u = url.lower()
    if "archiver" in u or "story_4" in u or "4_items" in u:
        return MOCK_INSTAGRAM_STORY_4_ITEMS
    elif "stories" in u or "/s/" in u:
        return MOCK_INSTAGRAM_STORY
    elif "carousel_5" in u or "5_items" in u:
        return MOCK_INSTAGRAM_CAROUSEL_5
    elif "single" in u or "post_photo" in u or "single_photo" in u:
        return MOCK_INSTAGRAM_POST
    elif "instagram.com" in u and ("reel" in u or "tv" in u):
        return [
            {
                "post_id": "C7Reel12345",
                "user": "doggo_world",
                "description": "Funny dog jumps over puddle",
                "extension": "mp4",
                "url": "https://instagram.com/reel/C7Reel12345/video.mp4",
                "thumbnail": "https://instagram.com/reel/C7Reel12345/thumb.jpg",
                "duration": 18.0,
                "date": "2024-05-12 18:30:00",
                "original_name_first": "dog_park_jump",
            }
        ]
    elif "instagram.com" in u:
        return MOCK_INSTAGRAM_CAROUSEL
    elif "twitter.com" in u or "x.com" in u:
        return MOCK_TWITTER_GALLERY
    elif "tiktok.com" in u:
        if "photo" in u or "slide" in u:
            return MOCK_TIKTOK_SLIDESHOW
        return [
            {
                "id": "7369123456789012345",
                "user": "cheftips_official",
                "description": "Cooking carbonara",
                "extension": "mp4",
                "url": "https://p16-sign.tiktokcdn.com/carbonara.mp4",
                "thumbnail": "https://p16-sign.tiktokcdn.com/carbonara_thumb.jpg",
                "duration": 58.0,
            }
        ]
    # Generic
    return MOCK_INSTAGRAM_CAROUSEL
