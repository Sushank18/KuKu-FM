"""
Microdrama Promotional Clip Pipeline - Phase 3 (Video Automation & Subtitles)
=============================================================================
This module handles:
  1. Deterministic boundary snapping to line-level timestamps.
  2. Subtitle (.srt) generation.
  3. FFmpeg slicing command generation.
"""

import os
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd


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
    """Converts float seconds into SubRip (.srt) timestamp format HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def seconds_to_ffmpeg_time(seconds: float) -> str:
    """Converts float seconds into FFmpeg timecode format HH:MM:SS.mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def snap_clip_to_screenplay_lines(
    screenplay_df: pd.DataFrame,
    episode_id: str,
    llm_start_tc: str,
    llm_end_tc: str,
    min_dur: float = 20.0,
    max_dur: float = 60.0,
) -> Optional[Tuple[float, float, float]]:
    """
    Aligns the LLM's suggested timecodes to the closest actual screenplay lines.
    Returns: (snapped_start_sec, snapped_end_sec, snapped_duration_sec)
    """
    ep_df = screenplay_df[screenplay_df["Episode"].astype(str) == str(episode_id)].copy()
    if ep_df.empty:
        return None

    raw_start = timecode_to_seconds(llm_start_tc)
    raw_end = timecode_to_seconds(llm_end_tc)

    start_idx = (ep_df["Start_Sec"] - raw_start).abs().idxmin()
    snapped_start = float(ep_df.loc[start_idx, "Start_Sec"])

    end_idx = (ep_df["End_Sec"] - raw_end).abs().idxmin()
    snapped_end = float(ep_df.loc[end_idx, "End_Sec"])

    snapped_dur = round(snapped_end - snapped_start, 2)

    if min_dur <= snapped_dur <= max_dur:
        return snapped_start, snapped_end, snapped_dur

    valid_candidates = []
    for s_i in range(len(ep_df)):
        s_val = ep_df.iloc[s_i]["Start_Sec"]
        for e_i in range(s_i, len(ep_df)):
            e_val = ep_df.iloc[e_i]["End_Sec"]
            d_val = round(e_val - s_val, 2)
            if min_dur <= d_val <= max_dur:
                dist = abs(s_val - raw_start) + abs(e_val - raw_end)
                valid_candidates.append((dist, s_val, e_val, d_val))
            elif d_val > max_dur:
                break

    if valid_candidates:
        valid_candidates.sort(key=lambda x: x[0])
        best = valid_candidates[0]
        return float(best[1]), float(best[2]), float(best[3])

    return None


def generate_promo_srt(
    screenplay_df: pd.DataFrame,
    episode_id: str,
    clip_start_sec: float,
    clip_end_sec: float,
    output_srt_path: str,
    include_speaker_names: bool = True
) -> bool:
    """Extracts all dialogue lines within the promo window and formats them into an .srt file."""
    ep_df = screenplay_df[screenplay_df["Episode"].astype(str) == str(episode_id)]
    ignore_entities = {"CAMERA", "ACTION", "SOUND FX", "MUSIC", "SFX"}

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

        if entity in ignore_entities or not content:
            continue

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

    os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))

    return True


def generate_ffmpeg_commands(
    promos_df: pd.DataFrame,
    video_source_dir: str,
    output_dir: str,
    script_type: str = "bat"
) -> str:
    commands: List[str] = []
    if script_type == "bat":
        commands.append("@echo off")
        commands.append(f'if not exist "{output_dir}" mkdir "{output_dir}"')
    else:
        commands.append("#!/usr/bin/env bash")
        commands.append(f'mkdir -p "{output_dir}"')

    for idx, row in promos_df.iterrows():
        ep = str(row["Episode"]).replace(" ", "_")
        start_sec = float(row["Snapped_Start_Sec"])
        duration = float(row["Duration_Sec"])

        t_start = seconds_to_ffmpeg_time(start_sec)
        t_duration = seconds_to_ffmpeg_time(duration)

        input_video = os.path.join(video_source_dir, f"episode_{ep}.mp4")
        output_clip = os.path.join(output_dir, f"promo_ep{ep}_{int(start_sec)}s.mp4")

        cmd = (
            f'ffmpeg -y -ss {t_start} -i "{input_video}" '
            f'-t {t_duration} -c:v libx264 -crf 18 -preset fast '
            f'-c:a aac -b:a 192k "{output_clip}"'
        )
        commands.append(cmd)

    return "\n".join(commands)

