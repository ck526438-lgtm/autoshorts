"""AutoShorts — an agentic factory for faceless short-form video.

    topic -> script -> voiceover -> b-roll -> karaoke captions -> 9:16 mp4
"""

from autoshorts.config import Niche, Settings, build_settings

__version__ = "0.1.0"
__all__ = ["Settings", "Niche", "build_settings", "__version__"]
