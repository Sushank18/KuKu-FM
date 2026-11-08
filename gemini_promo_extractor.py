"""
Microdrama Promotional Clip Extraction Pipeline - Phase 2 (Gemini API Integration)
===================================================================================
Uses Google GenAI SDK to identify 20-to-60-second standalone promotional clips
with strict hook and cliffhanger constraints and JSON schema validation.
"""

import os
import re
import json
import time
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GeminiPromoExtractor")

def get_gemini_client() -> genai.Client:
    """Initializes and returns the Google GenAI client using the active API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set the GEMINI_API_KEY environment variable."
        )
    return genai.Client(api_key=api_key)


def seconds_to_timecode(seconds: float) -> str:
    """Converts float seconds into MM:SS.ms formatted string."""
    if pd.isna(seconds) or seconds < 0:
        return "00:00.00"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:05.2f}"


def timecode_to_seconds(tc: str) -> float:
    """Converts MM:SS.ms string format into float seconds."""
    if not tc or not isinstance(tc, str):
        return 0.0
    cleaned = tc.strip().strip("()[] ")
    try:
        parts = cleaned.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return round(float(h) * 3600 + float(m) * 60 + float(s), 3)
        elif len(parts) == 2:
            m, s = parts
            return round(float(m) * 60 + float(s), 3)
        elif len(parts) == 1:
            return round(float(parts[0]), 3)
    except (ValueError, TypeError):
        pass
    return 0.0


def prepare_episode_scripts(df: pd.DataFrame) -> Dict[str, str]:
    """
    Groups screenplay lines by Episode and formats them chronologically
    with precise timecodes and character dialogues.
    """
    episode_scripts: Dict[str, str] = {}
    sorted_df = df.sort_values(by=["Episode", "Start_Sec"]).copy()

    for ep_id, group in sorted_df.groupby("Episode", sort=False):
        lines: List[str] = [f"=== EPISODE {ep_id} SCREENPLAY TRANSCRIPT ===\n"]
        for _, row in group.iterrows():
            start_tc = seconds_to_timecode(row["Start_Sec"])
            end_tc = seconds_to_timecode(row["End_Sec"])
            content = str(row.get("Content", "")).strip()

            entity = row.get("Entity_Type")
            emotion = row.get("Emotion")
            if pd.notna(entity) and entity:
                speaker = f"{entity} ({emotion}): " if pd.notna(emotion) and emotion else f"{entity}: "
            else:
                speaker = ""

            lines.append(f"[{start_tc} - {end_tc}] {speaker}{content}")

        episode_scripts[str(ep_id)] = "\n".join(lines)
    return episode_scripts


PROMO_JSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "promos": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "episode": {"type": "STRING"},
                    "start_time": {
                        "type": "STRING",
                        "description": "Timestamp format MM:SS.ms matching a line's start"
                    },
                    "end_time": {
                        "type": "STRING",
                        "description": "Timestamp format MM:SS.ms matching a line's end"
                    },
                    "hook_description": {
                        "type": "STRING",
                        "description": "High-tension opening beat, reveal, confrontation, or slap"
                    },
                    "cliffhanger_description": {
                        "type": "STRING",
                        "description": "Unresolved peak ending the clip"
                    },
                    "justification": {
                        "type": "STRING",
                        "description": "1-sentence explanation of why it works standalone"
                    }
                },
                "required": [
                    "episode",
                    "start_time",
                    "end_time",
                    "hook_description",
                    "cliffhanger_description",
                    "justification"
                ]
            }
        }
    },
    "required": ["promos"]
}

SYSTEM_INSTRUCTION = """
You are an expert short-form video editor for vertical microdramas (e.g., ReelShort, TikTok, Shorts).
Your objective is to extract the single most compelling promotional clip from the provided episode script.

CRITICAL RULES:
1. DURATION: Total duration (End Time minus Start Time) MUST be strictly between 20.0 and 60.0 seconds.
2. HOOK: Must open in the first 3 seconds on high drama, shocking revelation, betrayal, or intense confrontation.
3. CLIFFHANGER: Must cut off abruptly at an unresolved high-tension climax.
4. STANDALONE COHERENCE: Must make narrative sense on its own to a cold viewer.
5. PRECISE TIMECODES: `start_time` and `end_time` must precisely match the timestamps in the transcript.

Return strictly valid JSON matching the schema.
"""


def extract_promo_from_episode(
    client: genai.Client,
    episode_id: str,
    script_text: str,
    model_name: str = "gemini-3.5-flash-lite",
    max_retries: int = 3
) -> List[Dict[str, Any]]:
    """
    Sends the episode script to Gemini, parses and validates the returned promo clips.
    """
    prompt = f"Analyze Episode {episode_id} and extract the best 20-60 second promo clip:\n\n{script_text}"

    # Priority models to try in case of temporary 503 traffic spikes on one model
    models_to_try = [model_name, "gemini-3.5-flash", "gemini-flash-latest"]

    for current_model in models_to_try:
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("Extracting promo for Episode %s using %s (Attempt %d)...", episode_id, current_model, attempt)
                response = client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=PROMO_JSON_SCHEMA,
                        temperature=0.2,
                    )
                )

                raw_text = response.text.strip()
                data = json.loads(raw_text)
                promos = data.get("promos", [])

                validated: List[Dict[str, Any]] = []
                for p in promos:
                    start_sec = timecode_to_seconds(p.get("start_time", ""))
                    end_sec = timecode_to_seconds(p.get("end_time", ""))
                    duration = round(end_sec - start_sec, 2)
                    p["duration_sec"] = duration

                    if 20.0 <= duration <= 60.0:
                        validated.append(p)
                    else:
                        logger.warning(
                            "Clip for Episode %s duration %.2fs outside [20, 60]s: %s to %s",
                            episode_id, duration, p.get("start_time"), p.get("end_time")
                        )

                if validated:
                    return validated

            except Exception as e:
                logger.warning("Attempt %d with %s failed for Episode %s: %s", attempt, current_model, episode_id, e)
                if "503" in str(e):
                    # If model is unavailable, immediately fall back to the next model
                    break
                time.sleep(2.0 * attempt)

    return []


def run_gemini_extraction(
    screenplay_df: pd.DataFrame,
    episodes_limit: Optional[int] = None,
    output_csv: str = "output/gemini_extracted_promos.csv"
) -> pd.DataFrame:
    """
    Runs the complete Gemini extraction across episodes and flattens into a DataFrame.
    """
    client = get_gemini_client()
    episode_scripts = prepare_episode_scripts(screenplay_df)

    if episodes_limit:
        keys = list(episode_scripts.keys())[:episodes_limit]
        episode_scripts = {k: episode_scripts[k] for k in keys}

    records: List[Dict[str, Any]] = []

    for ep_id, script in episode_scripts.items():
        promos = extract_promo_from_episode(client, ep_id, script)
        for p in promos:
            records.append({
                "Episode": p.get("episode", ep_id),
                "Start_Time": p.get("start_time"),
                "End_Time": p.get("end_time"),
                "Duration_Sec": p.get("duration_sec"),
                "Hook_Description": p.get("hook_description"),
                "Cliffhanger_Description": p.get("cliffhanger_description"),
                "Justification": p.get("justification")
            })
        time.sleep(1.0)  # Rate pacing

    cols = [
        "Episode",
        "Start_Time",
        "End_Time",
        "Duration_Sec",
        "Hook_Description",
        "Cliffhanger_Description",
        "Justification"
    ]
    df_results = pd.DataFrame(records, columns=cols)
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    df_results.to_csv(output_csv, index=False)
    logger.info("Saved %d extracted promos to %s", len(df_results), output_csv)
    return df_results


if __name__ == "__main__":
    from script_parser import parse_screenplay

    # Test run on Episode 1 from the workspace
    sample_file = os.path.join("Data", "I Married a Broken Soldier. He was a Duke", "episode-001-Episode 1671703.txt")
    if os.path.exists(sample_file):
        df_ep1 = parse_screenplay(sample_file)
        results = run_gemini_extraction(df_ep1, episodes_limit=1)
        print("\n=== EXTRACTED PROMO RESULT ===")
        print(results.to_string())
