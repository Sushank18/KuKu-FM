"""
End-to-End Microdrama Promotional Clip Pipeline Runner
======================================================
Coordinates:
  1. Screenplay ingestion (from master CSV or parsing raw scripts).
  2. LLM promotional clip extraction with Gemini and fallback retry logic.
  3. Deterministic boundary snapping (dialogue starts only; no '...' fragments).
  4. Synchronized .srt subtitle generation.
  5. Frame-accurate FFmpeg slicing command generation via generate_ffmpeg_commands.
  6. Viral marketing creative generation (on-screen hooks, social copy, thumbnail frames).
  7. Isolated output in timestamped directory: output/run_<YYYYMMDD_HHMMSS>/
"""

import os
import sys
import time
import shutil
import logging
import argparse
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd

from script_parser import parse_screenplay, episode_number
from gemini_promo_extractor import (
    get_gemini_client,
    prepare_episode_scripts,
    extract_promo_from_episode,
    timecode_to_seconds,
    seconds_to_timecode,
)
from phase3_video_pipeline import (
    snap_clip_to_screenplay_lines,
    generate_promo_srt,
    generate_ffmpeg_commands,
    seconds_to_ffmpeg_time,
)
from marketing_creative_generator import (
    generate_marketing_creatives,
    calculate_optimal_thumbnail_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RunPipeline")


def parse_episode_selection(ep_arg: Optional[str], available_episodes: List[int]) -> List[int]:
    """
    Parses the --episodes flag:
      - None -> all available episodes
      - '1-10' -> range from 1 to 10
      - '5' -> first 5 episodes (1 to 5)
    """
    sorted_eps = sorted(available_episodes)
    if not ep_arg:
        return sorted_eps

    ep_str = str(ep_arg).strip()
    if "-" in ep_str:
        parts = ep_str.split("-")
        try:
            start_num, end_num = int(parts[0].strip()), int(parts[1].strip())
            return [ep for ep in sorted_eps if start_num <= ep <= end_num]
        except ValueError:
            logger.warning("Could not parse episode range '%s'. Running all episodes.", ep_str)
            return sorted_eps
    elif ep_str.isdigit():
        count = int(ep_str)
        return sorted_eps[:count]

    return sorted_eps


def clean_stale_promo_campaign(promo_campaign_dir: str = "output/promo_campaign"):
    """Removes stale subtitles from output/promo_campaign/ to avoid cross-run contamination."""
    stale_subtitles = os.path.join(promo_campaign_dir, "subtitles")
    if os.path.exists(stale_subtitles):
        try:
            shutil.rmtree(stale_subtitles)
            logger.info("Cleaned stale subtitles directory: %s", stale_subtitles)
        except Exception as e:
            logger.warning("Could not delete stale subtitles: %s", e)


def load_or_create_master_screenplay(
    master_csv: str = "output/master_parsed_screenplays.csv",
    scripts_dir: str = os.path.join("Data", "I Married a Broken Soldier. He was a Duke")
) -> pd.DataFrame:
    """Loads existing parsed screenplay master CSV or parses from raw scripts."""
    if os.path.exists(master_csv):
        logger.info("Loading existing master screenplay CSV: %s", master_csv)
        df = pd.read_csv(master_csv)
        df["Episode"] = df["Episode"].apply(episode_number).astype(int)
        return df

    logger.info("Master screenplay CSV not found at %s. Parsing from %s...", master_csv, scripts_dir)
    if not os.path.exists(scripts_dir):
        raise FileNotFoundError(f"Neither {master_csv} nor {scripts_dir} exists.")

    all_dfs = []
    for root, _, files in os.walk(scripts_dir):
        for f in sorted(files):
            if f.endswith(".txt"):
                p = os.path.join(root, f)
                df = parse_screenplay(p, include_extended_metadata=True)
                if not df.empty:
                    df["Source_File"] = f
                    all_dfs.append(df)

    if not all_dfs:
        raise ValueError(f"No valid .txt screenplay files found in {scripts_dir}")

    master_df = pd.concat(all_dfs, ignore_index=True)
    master_df["Episode"] = master_df["Episode"].apply(episode_number).astype(int)
    os.makedirs(os.path.dirname(os.path.abspath(master_csv)), exist_ok=True)
    master_df.to_csv(master_csv, index=False)
    logger.info("Saved %d parsed screenplay lines to %s", len(master_df), master_csv)
    return master_df


def run_pipeline(
    episodes: Optional[str] = None,
    output_dir: str = "output",
    master_csv: str = "output/master_parsed_screenplays.csv",
    scripts_dir: str = os.path.join("Data", "I Married a Broken Soldier. He was a Duke"),
    min_dur: float = 20.0,
    max_dur: float = 60.0
):
    # Create isolated timestamped run directory
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(output_dir, f"run_{run_timestamp}")
    os.makedirs(run_dir, exist_ok=True)
    subtitles_dir = os.path.join(run_dir, "subtitles")
    os.makedirs(subtitles_dir, exist_ok=True)
    failures_csv = os.path.join(run_dir, "failures.csv")

    # Clean stale subtitles from older shared locations
    clean_stale_promo_campaign()

    logger.info("==================================================================")
    logger.info("INITIALIZING RUN: %s", run_dir)
    logger.info("==================================================================")

    # 1. Load screenplay data
    screenplay_df = load_or_create_master_screenplay(master_csv=master_csv, scripts_dir=scripts_dir)

    # 2. Prepare grouped episode scripts (sorted numerically)
    client = get_gemini_client()
    episode_scripts = prepare_episode_scripts(screenplay_df)
    all_ep_keys = list(episode_scripts.keys())

    target_episodes = parse_episode_selection(episodes, all_ep_keys)
    logger.info(
        "Targeting %d of %d episodes: %s",
        len(target_episodes), len(all_ep_keys), target_episodes[:10] + (["..."] if len(target_episodes) > 10 else [])
    )

    campaign_records: List[Dict[str, Any]] = []

    for idx, ep_num in enumerate(target_episodes, 1):
        script_text = episode_scripts[ep_num]
        logger.info("[%d/%d] Processing Episode %d with Gemini...", idx, len(target_episodes), ep_num)

        promos = extract_promo_from_episode(
            client=client,
            episode_id=ep_num,
            script_text=script_text,
            failures_csv=failures_csv
        )

        if not promos:
            logger.warning("Episode %d produced no promotional clips. Recorded in %s", ep_num, failures_csv)
            continue

        for p in promos:
            raw_start_tc = str(p.get("start_time", ""))
            raw_end_tc = str(p.get("end_time", ""))
            raw_start_sec = timecode_to_seconds(raw_start_tc)
            raw_end_sec = timecode_to_seconds(raw_end_tc)
            raw_dur_sec = round(raw_end_sec - raw_start_sec, 2)

            # Snap strictly to dialogue line starts (no CAMERA/ACTION, no continuation '...')
            snapped = snap_clip_to_screenplay_lines(
                screenplay_df=screenplay_df,
                episode_id=ep_num,
                llm_start_tc=raw_start_tc,
                llm_end_tc=raw_end_tc,
                min_dur=min_dur,
                max_dur=max_dur
            )

            if snapped is not None:
                s_start, s_end, s_dur = snapped
                status = "valid"
            else:
                # Do NOT silently fall back to unverified out-of-bounds times
                logger.warning(
                    "Episode %d: Snapping failed to find valid 20-60s dialogue-started window. Marked as needs_review.",
                    ep_num
                )
                s_start = raw_start_sec
                s_end = raw_end_sec
                s_dur = raw_dur_sec
                status = "needs_review"

            # Generate Subtitle file (.srt)
            srt_filename = f"promo_ep{ep_num}_{int(s_start)}s_{int(s_end)}s.srt"
            srt_path = os.path.join(subtitles_dir, srt_filename)

            generate_promo_srt(
                screenplay_df=screenplay_df,
                episode_id=ep_num,
                clip_start_sec=s_start,
                clip_end_sec=s_end,
                output_srt_path=srt_path,
                include_speaker_names=True
            )

            # Generate marketing ad creatives
            clip_mask = (
                (screenplay_df["Episode"].apply(episode_number) == ep_num) &
                (screenplay_df["Start_Sec"] >= s_start - 0.05) &
                (screenplay_df["End_Sec"] <= s_end + 0.05)
            )
            clip_lines = screenplay_df[clip_mask]
            clip_dialogue = "\n".join([
                f"{r.get('Entity_Type', '')}: {r.get('Content', '')}" for _, r in clip_lines.iterrows()
            ])

            creatives = generate_marketing_creatives(
                client=client,
                episode_id=ep_num,
                hook_desc=p.get("hook_description", ""),
                cliffhanger_desc=p.get("cliffhanger_description", ""),
                transcript_text=clip_dialogue
            )
            thumbnail_sec = calculate_optimal_thumbnail_timestamp(
                screenplay_df=screenplay_df,
                episode_id=ep_num,
                clip_start_sec=s_start,
                clip_end_sec=s_end
            )

            hook_opts = creatives.get("on_screen_hook_options", [])
            hook_1 = hook_opts[0] if len(hook_opts) > 0 else ""
            hook_2 = hook_opts[1] if len(hook_opts) > 1 else ""
            hook_3 = hook_opts[2] if len(hook_opts) > 2 else ""

            campaign_records.append({
                "Episode": int(ep_num),
                "Status": status,
                "Start_Time": seconds_to_timecode(s_start),
                "End_Time": seconds_to_timecode(s_end),
                "Exact_Start_Sec": s_start,
                "Exact_End_Sec": s_end,
                "Duration_Sec": s_dur,
                "Thumbnail_Frame_Sec": thumbnail_sec,
                "Hook_Description": p.get("hook_description"),
                "Cliffhanger_Description": p.get("cliffhanger_description"),
                "On_Screen_Hook_1": hook_1,
                "On_Screen_Hook_2": hook_2,
                "On_Screen_Hook_3": hook_3,
                "Social_Caption": creatives.get("social_caption"),
                "Hashtags": " ".join(creatives.get("hashtags", [])),
                "Call_To_Action": creatives.get("call_to_action"),
                "SRT_Subtitle_Path": srt_path,
                "Justification": p.get("justification")
            })

        time.sleep(1.0)  # Pacing between LLM requests

    if not campaign_records:
        logger.error("No campaign records generated across requested episodes.")
        return

    campaign_df = pd.DataFrame(campaign_records)
    campaign_df["Episode"] = campaign_df["Episode"].apply(episode_number).astype(int)

    # Save manifest into timestamped run directory
    manifest_csv = os.path.join(run_dir, "promo_campaign_manifest.csv")
    campaign_df.to_csv(manifest_csv, index=False)
    logger.info("[SUCCESS] Generated campaign manifest with %d clips -> %s", len(campaign_df), manifest_csv)

    # Also update promo_campaign directory for Streamlit dashboard access
    shared_manifest_dir = os.path.join("output", "promo_campaign")
    os.makedirs(shared_manifest_dir, exist_ok=True)
    shared_manifest_csv = os.path.join(shared_manifest_dir, "promo_campaign_manifest.csv")
    campaign_df.to_csv(shared_manifest_csv, index=False)

    # Copy new subtitles into shared promo_campaign/subtitles/
    shared_subtitles_dir = os.path.join(shared_manifest_dir, "subtitles")
    os.makedirs(shared_subtitles_dir, exist_ok=True)
    for srt_file in os.listdir(subtitles_dir):
        shutil.copy2(os.path.join(subtitles_dir, srt_file), os.path.join(shared_subtitles_dir, srt_file))

    # Generate FFmpeg batch script using phase3_video_pipeline.generate_ffmpeg_commands
    bat_commands = generate_ffmpeg_commands(
        promos_df=campaign_df,
        video_source_dir="raw_videos",
        output_dir="clips",
        script_type="bat"
    )
    bat_path = os.path.join(run_dir, "slice_promos.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_commands)
    shutil.copy2(bat_path, os.path.join(shared_manifest_dir, "slice_promos.bat"))
    logger.info("[SUCCESS] Generated FFmpeg slicing script -> %s", bat_path)

    print("\n" + "="*80)
    print("PROMOTIONAL MARKETING CAMPAIGN RUN SUMMARY:")
    print("="*80)
    print(campaign_df[["Episode", "Status", "Start_Time", "End_Time", "Duration_Sec", "On_Screen_Hook_1"]].to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-End Microdrama Promotional Pipeline")
    parser.add_argument(
        "--episodes",
        type=str,
        default=None,
        help="Optional episode count (e.g. 5) or range (e.g. 1-10). If omitted, runs all episodes."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="output",
        help="Base output directory (default: output)"
    )
    parser.add_argument(
        "--master_csv",
        type=str,
        default="output/master_parsed_screenplays.csv",
        help="Path to master parsed screenplay CSV"
    )
    parser.add_argument(
        "--scripts_dir",
        type=str,
        default=os.path.join("Data", "I Married a Broken Soldier. He was a Duke"),
        help="Directory containing screenplay .txt files"
    )

    args = parser.parse_args()
    run_pipeline(
        episodes=args.episodes,
        output_dir=args.output_dir,
        master_csv=args.master_csv,
        scripts_dir=args.scripts_dir
    )
