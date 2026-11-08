"""
Microdrama Promotional Clip Pipeline - Phase 3 (Video Automation & Subtitles)
=============================================================================
This module handles:
  1. Deterministic boundary snapping:
     - START snapped strictly to dialogue line starts (rejects CAMERA/ACTION and continuation lines like '...').
     - END snapped to line ends.
  2. Frame-accurate Subtitle (.srt) generation with millisecond carry-over.
  3. Frame-accurate FFmpeg cutting commands (re-encoding for clean non-keyframe cuts).
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from script_parser import episode_number

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Phase3VideoPipeline")

NON_DIALOGUE_ENTITIES = {"CAMERA", "ACTION", "SOUND FX", "MUSIC", "SFX"}


def timecode_to_seconds(tc: str) -> float:
    """Converts MM:SS.ms string into float seconds."""
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


def seconds_to_srt_timestamp(seconds: float) -> str:
    """
    Converts float seconds into SubRip (.srt) timestamp format HH:MM:SS,mmm.
    Properly carries rounded milliseconds into seconds, minutes, and hours.
    
    Example:
        59.9996 -> '00:01:00,000'
    """
    if seconds < 0:
        seconds = 0.0
    total_millis = int(round(seconds * 1000))
    millis = total_millis % 1000
    total_seconds = total_millis // 1000
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def seconds_to_ffmpeg_time(seconds: float) -> str:
    """Converts float seconds into FFmpeg timecode format HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def is_valid_dialogue_start(row: pd.Series) -> Tuple[bool, str]:
    """
    Validates whether a screenplay row is eligible to be the opening line of a promo clip:
    1. Must be spoken dialogue (not CAMERA, ACTION, SOUND FX, etc.).
    2. Must NOT start with an ellipsis ('...' or '…') indicating an in-progress sentence.
    3. Must NOT start with a lowercase letter indicating a continuation fragment.
    """
    entity = str(row.get("Entity_Type", "")).strip().upper()
    if entity in NON_DIALOGUE_ENTITIES:
        return False, "non_dialogue"

    raw_content = str(row.get("Content", "")).strip()
    if not raw_content:
        return False, "empty"

    # Strip quotes and leading whitespace
    stripped = raw_content.lstrip('"\'').strip()
    if not stripped:
        return False, "empty"

    if stripped.startswith("...") or stripped.startswith("…"):
        return False, "starts_with_ellipsis"

    if stripped[0].islower():
        return False, "starts_with_lowercase"

    return True, "valid"


def snap_clip_to_screenplay_lines(
    screenplay_df: pd.DataFrame,
    episode_id: Any,
    llm_start_tc: str,
    llm_end_tc: str,
    min_dur: float = 20.0,
    max_dur: float = 60.0,
) -> Optional[Tuple[float, float, float]]:
    """
    Aligns the LLM's suggested timecodes to exact line boundaries:
    - START snaps strictly to the start of a valid dialogue line (no CAMERA/ACTION, no '...').
    - END snaps to the end of any screenplay line.
    
    Returns:
        (snapped_start_sec, snapped_end_sec, snapped_duration_sec) or None if no valid
        dialogue-started window exists within [min_dur, max_dur].
    """
    ep_num = episode_number(episode_id)
    ep_df = screenplay_df[screenplay_df["Episode"].apply(episode_number) == ep_num].copy()
    if ep_df.empty:
        logger.warning("Episode %s not found in screenplay DataFrame during snapping.", ep_num)
        return None

    raw_start = timecode_to_seconds(llm_start_tc)
    raw_end = timecode_to_seconds(llm_end_tc)

    # Pre-filter all rows that are valid dialogue opening lines
    valid_starts = []
    for idx, row in ep_df.iterrows():
        is_valid, reason = is_valid_dialogue_start(row)
        if is_valid:
            valid_starts.append(idx)
        else:
            # Check if this rejected line was very close to raw_start; if so, log warning
            if abs(float(row["Start_Sec"]) - raw_start) <= 2.0 and reason in ("starts_with_ellipsis", "starts_with_lowercase"):
                logger.warning(
                    "Episode %s: Candidate start at %.2fs rejected (%s: '%s'). Moving to valid dialogue start.",
                    ep_num, row["Start_Sec"], reason, str(row.get("Content", ""))[:40]
                )

    if not valid_starts:
        logger.warning("Episode %s: No valid dialogue start lines found.", ep_num)
        return None

    # Evaluate candidate windows (start on valid dialogue, end on any subsequent line)
    candidate_windows = []
    all_indices = list(ep_df.index)

    for s_idx in valid_starts:
        s_val = float(ep_df.loc[s_idx, "Start_Sec"])

        for e_idx in all_indices:
            if e_idx < s_idx:
                continue

            e_val = float(ep_df.loc[e_idx, "End_Sec"])
            dur = round(e_val - s_val, 2)

            if min_dur <= dur <= max_dur:
                penalty = abs(s_val - raw_start) + abs(e_val - raw_end)
                candidate_windows.append((penalty, s_val, e_val, dur))
            elif dur > max_dur:
                break

    if candidate_windows:
        # Sort by distance penalty from LLM target timestamps
        candidate_windows.sort(key=lambda x: x[0])
        best = candidate_windows[0]
        return float(best[1]), float(best[2]), float(best[3])

    logger.warning("Episode %s: Snapping could not find a valid window within [%.1fs, %.1fs].", ep_num, min_dur, max_dur)
    return None


def generate_promo_srt(
    screenplay_df: pd.DataFrame,
    episode_id: Any,
    clip_start_sec: float,
    clip_end_sec: float,
    output_srt_path: str,
    include_speaker_names: bool = True
) -> bool:
    """
    Extracts all dialogue lines within the promo window, shifts timestamps so the
    clip begins at 00:00:00,000, and writes an .srt subtitle file.
    """
    ep_num = episode_number(episode_id)
    ep_df = screenplay_df[screenplay_df["Episode"].apply(episode_number) == ep_num]

    # Filter lines that fall within the clip timeframe
    mask = (
        (ep_df["Start_Sec"] >= clip_start_sec - 0.05) &
        (ep_df["End_Sec"] <= clip_end_sec + 0.05)
    )
    clip_lines = ep_df[mask].sort_values(by="Start_Sec")

    srt_entries: List[str] = []
    cue_index = 1

    for _, row in clip_lines.iterrows():
        entity = str(row.get("Entity_Type", "")).strip().upper()
        content = str(row.get("Content", "")).strip().strip('"')

        # Skip visual/action descriptions in subtitles
        if entity in NON_DIALOGUE_ENTITIES or not content:
            continue

        # Re-zero timestamps relative to clip start
        rel_start = max(0.0, float(row["Start_Sec"]) - clip_start_sec)
        rel_end = max(rel_start + 0.5, float(row["End_Sec"]) - clip_start_sec)

        start_srt = seconds_to_srt_timestamp(rel_start)
        end_srt = seconds_to_srt_timestamp(rel_end)

        speaker_prefix = f"{row.get('Entity_Type')}: " if include_speaker_names and pd.notna(row.get("Entity_Type")) else ""
        sub_text = f"{speaker_prefix}{content}"

        srt_block = f"{cue_index}\n{start_srt} --> {end_srt}\n{sub_text}\n"
        srt_entries.append(srt_block)
        cue_index += 1

    if not srt_entries:
        return False

    os.makedirs(os.path.dirname(os.path.abspath(output_srt_path)), exist_ok=True)
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))

    return True


def generate_ffmpeg_commands(
    promos_df: pd.DataFrame,
    video_source_dir: str = "raw_videos",
    output_dir: str = "clips",
    script_type: str = "bat"
) -> str:
    """
    Generates an executable batch or shell script containing frame-accurate FFmpeg slicing commands.
    Note: Uses re-encoding (-c:v libx264 -c:a aac) for clean, frame-accurate cuts at non-keyframes.
    """
    commands: List[str] = []
    if script_type == "bat":
        commands.append("@echo off")
        commands.append(f'if not exist "{output_dir}" mkdir "{output_dir}"')
    else:
        commands.append("#!/usr/bin/env bash")
        commands.append(f'mkdir -p "{output_dir}"')

    for _, row in promos_df.iterrows():
        ep_num = episode_number(row["Episode"])
        start_sec = float(row.get("Exact_Start_Sec", row.get("Snapped_Start_Sec", 0.0)))
        dur_sec = float(row.get("Duration_Sec", row.get("Snapped_Duration_Sec", 30.0)))

        t_start = seconds_to_ffmpeg_time(start_sec)
        t_dur = seconds_to_ffmpeg_time(dur_sec)

        in_vid = f"{video_source_dir}/episode_{ep_num}.mp4"
        out_clip = f"{output_dir}/promo_ep{ep_num}_{int(start_sec)}s_to_{int(start_sec + dur_sec)}s.mp4"

        cmd = (
            f'ffmpeg -y -ss {t_start} -i "{in_vid}" '
            f'-t {t_dur} -c:v libx264 -crf 18 -preset fast '
            f'-c:a aac -b:a 192k "{out_clip}"'
        )
        commands.append(cmd)

    return "\n".join(commands)
