"""
Microdrama Promotional Clip Extraction Pipeline - Phase 2 (Gemini API Integration)
===================================================================================
Uses Google GenAI SDK to identify 20-to-60-second standalone promotional clips
with strict hook and cliffhanger constraints, duration validation, retry logic,
and structured JSON schema output.
"""

import os
import re
import json
import time
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from llm_client import generate_json
from script_parser import episode_number

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GeminiPromoExtractor")

# Dynamic model configuration from environment
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS_ENV = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-flash-latest")
FALLBACK_MODELS = [m.strip() for m in FALLBACK_MODELS_ENV.split(",") if m.strip()]


def get_gemini_client():
    """Returns None as centralized client calls llm_client directly."""
    return None


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


def prepare_episode_scripts(df: pd.DataFrame) -> Dict[int, str]:
    """
    Groups screenplay lines by Episode and formats them chronologically
    with precise timecodes and character dialogues, sorted numerically by Episode.
    """
    episode_scripts: Dict[int, str] = {}
    work_df = df.copy()
    work_df["Episode"] = work_df["Episode"].apply(episode_number)
    sorted_df = work_df.sort_values(by=["Episode", "Start_Sec"])

    for ep_id, group in sorted_df.groupby("Episode", sort=True):
        ep_num = int(ep_id)
        lines: List[str] = [f"=== EPISODE {ep_num} SCREENPLAY TRANSCRIPT ===\n"]
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

        episode_scripts[ep_num] = "\n".join(lines)
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


def is_rate_limit_or_server_error(exc: Exception) -> bool:
    """Detects HTTP 429 (rate limit) or 503 (server unavailable) from exceptions."""
    err_str = str(exc).lower()
    status_code = getattr(exc, "status_code", getattr(exc, "code", None))
    return (
        status_code in (429, 503)
        or "429" in err_str
        or "503" in err_str
        or "resource_exhausted" in err_str
        or "rate limit" in err_str
        or "unavailable" in err_str
    )


def record_failure(failures_csv: str, episode_id: Any, reason: str):
    """Appends an episode processing failure to failures.csv."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(failures_csv)), exist_ok=True)
        file_exists = os.path.exists(failures_csv)
        with open(failures_csv, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("Episode,Reason\n")
            clean_reason = str(reason).replace('"', '""').replace("\n", " ")
            f.write(f'{episode_id},"{clean_reason}"\n')
    except Exception as e:
        logger.error("Could not write failure to %s: %s", failures_csv, e)


def extract_promo_from_episode(
    client: genai.Client,
    episode_id: Any,
    script_text: str,
    failures_csv: str = "output/failures.csv",
    max_retries: int = 2
) -> List[Dict[str, Any]]:
    """
    Sends the episode script to Gemini:
    - Tries DEFAULT_MODEL and falls back to FALLBACK_MODELS.
    - Handles rate limits (429) and server spikes (503) with exponential backoff.
    - Retries ONCE with specific duration error feedback if clip duration is outside 20-60s.
    - Never retries identically more than twice.
    - Records persistent failures to failures.csv.
    """
    ep_num = episode_number(episode_id)
    base_prompt = f"Analyze Episode {ep_num} and extract the best 20-60 second promo clip:\n\n{script_text}"

    # Build model candidate list from environment
    all_models = [DEFAULT_MODEL] + [m for m in FALLBACK_MODELS if m != DEFAULT_MODEL]
    last_error_reason = "No models available"

    for current_model in all_models:
        current_prompt = base_prompt
        duration_retry_done = False

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Querying Gemini for Episode %s using %s (Attempt %d/%d)...",
                    ep_num, current_model, attempt, max_retries
                )
                data = generate_json(
                    prompt=current_prompt,
                    schema=PROMO_JSON_SCHEMA,
                    system_instruction=SYSTEM_INSTRUCTION,
                    model=current_model,
                    temperature=0.2,
                )
                promos = data.get("promos", [])

                validated: List[Dict[str, Any]] = []
                out_of_bounds_durations = []

                for p in promos:
                    start_sec = timecode_to_seconds(p.get("start_time", ""))
                    end_sec = timecode_to_seconds(p.get("end_time", ""))
                    duration = round(end_sec - start_sec, 2)
                    p["duration_sec"] = duration

                    if 20.0 <= duration <= 60.0:
                        validated.append(p)
                    else:
                        out_of_bounds_durations.append((duration, p.get("start_time"), p.get("end_time")))

                if validated:
                    return validated

                # If duration was outside 20-60s, retry ONCE with specific duration feedback
                if out_of_bounds_durations and not duration_retry_done:
                    bad_dur, bad_s, bad_e = out_of_bounds_durations[0]
                    duration_retry_done = True
                    logger.warning(
                        "Episode %s: Model returned clip outside 20-60s (%.1fs, %s to %s). Retrying with targeted prompt...",
                        ep_num, bad_dur, bad_s, bad_e
                    )
                    current_prompt = (
                        f"{base_prompt}\n\n"
                        f"CRITICAL CORRECTION REQUIRED: Your previous choice from {bad_s} to {bad_e} was {bad_dur:.1f}s. "
                        f"The promo clip duration MUST be strictly between 20.0 and 60.0 seconds. "
                        f"Pick line timestamps so that (End Time - Start Time) is strictly between 20 and 60 seconds."
                    )
                    time.sleep(1.0)
                    continue  # Retry with correction prompt

                last_error_reason = f"Clips outside duration constraints: {out_of_bounds_durations}"

            except Exception as e:
                last_error_reason = str(e)
                logger.warning("Attempt %d with %s failed for Episode %s: %s", attempt, current_model, ep_num, e)

                if is_rate_limit_or_server_error(e):
                    # Exponential backoff for rate limit (429) or 503
                    backoff = 2.0 ** attempt
                    logger.info("Rate limit / 503 detected. Backing off for %.1fs...", backoff)
                    time.sleep(backoff)
                else:
                    # Non-retriable or structural error
                    time.sleep(1.0)

        # If current_model exhausted all retries, loop continues to next fallback model
        logger.info("Switching from %s to next fallback model...", current_model)

    # If all models and retries failed, log and write to failures.csv
    logger.error("Episode %s failed all attempts across all models. Logging to %s", ep_num, failures_csv)
    record_failure(failures_csv, ep_num, last_error_reason)
    return []


def run_gemini_extraction(
    screenplay_df: pd.DataFrame,
    episodes_limit: Optional[int] = None,
    output_csv: str = "output/gemini_extracted_promos.csv",
    failures_csv: str = "output/failures.csv"
) -> pd.DataFrame:
    """
    Runs Gemini extraction across episodes and returns a DataFrame with Episode as int.
    """
    client = get_gemini_client()
    episode_scripts = prepare_episode_scripts(screenplay_df)

    sorted_ep_keys = sorted(episode_scripts.keys())
    if episodes_limit:
        sorted_ep_keys = sorted_ep_keys[:episodes_limit]

    records: List[Dict[str, Any]] = []

    for ep_id in sorted_ep_keys:
        script = episode_scripts[ep_id]
        promos = extract_promo_from_episode(client, ep_id, script, failures_csv=failures_csv)
        for p in promos:
            records.append({
                "Episode": episode_number(p.get("episode", ep_id)),
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
    if "Episode" in df_results.columns:
        df_results["Episode"] = df_results["Episode"].apply(episode_number).astype(int)

    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    df_results.to_csv(output_csv, index=False)
    logger.info("Saved %d extracted promos to %s", len(df_results), output_csv)
    return df_results
