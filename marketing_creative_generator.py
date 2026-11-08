"""
Microdrama Promotional Creative & Metadata Generator (Phase 4)
==============================================================
Generates viral on-screen hook overlays, social captions, hashtag taxonomies,
and calculates optimal thumbnail freeze-frame timestamps for promo clips.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from google import genai
from google.genai import types
from script_parser import episode_number

logger = logging.getLogger("CreativeGenerator")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

CREATIVE_JSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "on_screen_hook_options": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "3 ultra-short, dramatic on-screen text overlays under 7 words (e.g. 'She wore white. He chose her sister.')"
        },
        "social_caption": {
            "type": "STRING",
            "description": "High-converting social caption with an emotional hook question and clear CTA"
        },
        "hashtags": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "5-7 viral microdrama hashtags (e.g. #microdrama, #betrayal, #billionaire)"
        },
        "call_to_action": {
            "type": "STRING",
            "description": "Urgent viewer directive (e.g. 'Tap the link to watch Episode 2 now!')"
        }
    },
    "required": [
        "on_screen_hook_options",
        "social_caption",
        "hashtags",
        "call_to_action"
    ]
}


def calculate_optimal_thumbnail_timestamp(
    screenplay_df: pd.DataFrame,
    episode_id: Any,
    clip_start_sec: float,
    clip_end_sec: float
) -> float:
    """
    Deterministically locates the optimal freeze-frame timestamp for a video thumbnail.
    Prioritizes camera close-ups and lines with peak emotional shock/tears/rage.
    """
    ep_num = episode_number(episode_id)
    ep_df = screenplay_df[screenplay_df["Episode"].apply(episode_number) == ep_num]
    mask = (ep_df["Start_Sec"] >= clip_start_sec) & (ep_df["End_Sec"] <= clip_end_sec)
    clip_df = ep_df[mask]

    if clip_df.empty:
        return round(clip_start_sec + 2.0, 2)

    high_impact_keywords = {"weeping", "outraged", "shock", "smug", "cold", "tears", "slap", "betrayed", "broken"}

    for _, row in clip_df.iterrows():
        emotion = str(row.get("Emotion", "")).lower()
        content = str(row.get("Content", "")).lower()

        if any(k in emotion for k in high_impact_keywords) or "close-up" in content or "tears" in content:
            return round((row["Start_Sec"] + row["End_Sec"]) / 2, 2)

    return round(min(clip_start_sec + 3.0, clip_end_sec - 1.0), 2)


def generate_marketing_creatives(
    client: genai.Client,
    episode_id: Any,
    hook_desc: str,
    cliffhanger_desc: str,
    transcript_text: str,
    model_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Uses Gemini to generate high-converting promotional copy and on-screen text overlays.
    """
    target_model = model_name or DEFAULT_MODEL
    prompt = f"""
You are a viral growth marketer for vertical microdrama apps (like ReelShort, ShortMax, KuKu FM).
Generate creative promotional ad metadata for this approved clip:

EPISODE: {episode_id}
HOOK EVENT: {hook_desc}
CLIFFHANGER EVENT: {cliffhanger_desc}

DIALOGUE TRANSCRIPT:
{transcript_text}

Provide 3 punchy on-screen text overlays (under 7 words each), a viral social caption, targeted hashtags, and a compelling CTA.
"""

    try:
        response = client.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CREATIVE_JSON_SCHEMA,
                temperature=0.4,
            )
        )
        return json.loads(response.text.strip())
    except Exception as e:
        logger.warning("Creative generation fallback for Episode %s: %s", episode_id, e)
        return {
            "on_screen_hook_options": [
                "Betrayed At The Altar",
                "She Wore White. He Chose Her Sister.",
                "The Ultimate Betrayal"
            ],
            "social_caption": "Her wedding dress wasn't even cold when her sister took her groom... Would you ever forgive this? 💔",
            "hashtags": ["#microdrama", "#betrayal", "#drama", "#reels", "#fyp"],
            "call_to_action": "Tap the link to watch what happens next!"
        }

