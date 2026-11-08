"""
End-to-End Microdrama Promotional Clip Pipeline Runner
======================================================
1. Ingests parsed screenplays from output/master_parsed_screenplays.csv
2. Queries Gemini (gemini-3.5-flash-lite) for 20-60s promo clips
3. Snaps timestamps to exact dialogue line boundaries
4. Generates synchronized .srt subtitles for each promo clip
5. Generates viral marketing copy, hook overlays, and thumbnail timestamps
6. Generates FFmpeg video slicing & thumbnail extraction batch script
7. Exports the unified marketing manifest
"""

import os
import sys
import time
import logging
import pandas as pd
from typing import Optional

from gemini_promo_extractor import (
    get_gemini_client,
    prepare_episode_scripts,
    extract_promo_from_episode,
    timecode_to_seconds,
    seconds_to_timecode
)
from phase3_video_pipeline import (
    snap_clip_to_screenplay_lines,
    generate_promo_srt,
    seconds_to_ffmpeg_time
)
from marketing_creative_generator import (
    generate_marketing_creatives,
    calculate_optimal_thumbnail_timestamp
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EndToEndPipeline")


def run_pipeline(
    master_screenplay_csv: str = "output/master_parsed_screenplays.csv",
    output_dir: str = "output/promo_campaign",
    episodes_count: Optional[int] = 5
):
    os.makedirs(output_dir, exist_ok=True)
    subtitles_dir = os.path.join(output_dir, "subtitles")
    os.makedirs(subtitles_dir, exist_ok=True)

    if not os.path.exists(master_screenplay_csv):
        logger.error("Master screenplay CSV not found at: %s", master_screenplay_csv)
        return

    logger.info("Loading master screenplay database from: %s", master_screenplay_csv)
    screenplay_df = pd.read_csv(master_screenplay_csv)

    client = get_gemini_client()
    episode_scripts = prepare_episode_scripts(screenplay_df)

    ep_keys = list(episode_scripts.keys())
    if episodes_count:
        ep_keys = ep_keys[:episodes_count]
        logger.info("Running on %d episodes: %s", len(ep_keys), ep_keys)
    else:
        logger.info("Running on all %d episodes in database.", len(ep_keys))

    campaign_records = []

    for idx, ep_id in enumerate(ep_keys, 1):
        script_text = episode_scripts[ep_id]
        logger.info("[%d/%d] Processing Episode %s with Gemini...", idx, len(ep_keys), ep_id)

        promos = extract_promo_from_episode(client, ep_id, script_text)
        if not promos:
            logger.warning("No promo returned for Episode %s. Skipping.", ep_id)
            continue

        for p in promos:
            raw_start_tc = p.get("start_time")
            raw_end_tc = p.get("end_time")

            # Snap to line-level timestamps
            snapped = snap_clip_to_screenplay_lines(
                screenplay_df=screenplay_df,
                episode_id=ep_id,
                llm_start_tc=raw_start_tc,
                llm_end_tc=raw_end_tc,
                min_dur=20.0,
                max_dur=60.0
            )

            if not snapped:
                s_start = timecode_to_seconds(raw_start_tc)
                s_end = timecode_to_seconds(raw_end_tc)
                s_dur = round(s_end - s_start, 2)
            else:
                s_start, s_end, s_dur = snapped

            clean_ep_name = str(ep_id).replace(" ", "_")
            srt_filename = f"promo_ep{clean_ep_name}_{int(s_start)}s_{int(s_end)}s.srt"
            srt_path = os.path.join(subtitles_dir, srt_filename)

            # Generate Subtitle file (.srt)
            generate_promo_srt(
                screenplay_df=screenplay_df,
                episode_id=ep_id,
                clip_start_sec=s_start,
                clip_end_sec=s_end,
                output_srt_path=srt_path,
                include_speaker_names=True
            )

            # Extract dialogue transcript for creative generation
            clip_mask = (
                (screenplay_df["Episode"].astype(str) == str(ep_id)) &
                (screenplay_df["Start_Sec"] >= s_start - 0.05) &
                (screenplay_df["End_Sec"] <= s_end + 0.05)
            )
            clip_lines = screenplay_df[clip_mask]
            clip_dialogue = "\n".join([
                f"{r.get('Entity_Type', '')}: {r.get('Content', '')}" for _, r in clip_lines.iterrows()
            ])

            # Phase 4: Marketing Creative Packaging
            creatives = generate_marketing_creatives(
                client=client,
                episode_id=ep_id,
                hook_desc=p.get("hook_description", ""),
                cliffhanger_desc=p.get("cliffhanger_description", ""),
                transcript_text=clip_dialogue
            )
            thumbnail_sec = calculate_optimal_thumbnail_timestamp(
                screenplay_df=screenplay_df,
                episode_id=ep_id,
                clip_start_sec=s_start,
                clip_end_sec=s_end
            )

            hook_opts = creatives.get("on_screen_hook_options", [])
            hook_1 = hook_opts[0] if len(hook_opts) > 0 else ""
            hook_2 = hook_opts[1] if len(hook_opts) > 1 else ""
            hook_3 = hook_opts[2] if len(hook_opts) > 2 else ""

            campaign_records.append({
                "Episode": ep_id,
                "Start_Timecode": seconds_to_timecode(s_start),
                "End_Timecode": seconds_to_timecode(s_end),
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

        time.sleep(1.0)  # Pacing between calls

    if not campaign_records:
        logger.warning("No campaign records generated.")
        return

    campaign_df = pd.DataFrame(campaign_records)
    manifest_csv = os.path.join(output_dir, "promo_campaign_manifest.csv")
    campaign_df.to_csv(manifest_csv, index=False)
    logger.info("[SUCCESS] Generated comprehensive campaign manifest with %d clips -> %s", len(campaign_df), manifest_csv)

    # Generate FFmpeg batch script for slicing clips AND extracting thumbnails
    bat_lines = ["@echo off", "mkdir clips 2>nul", "mkdir thumbnails 2>nul\n"]
    for _, r in campaign_df.iterrows():
        ep = str(r["Episode"]).replace(" ", "_")
        t_start = seconds_to_ffmpeg_time(r["Exact_Start_Sec"])
        t_dur = seconds_to_ffmpeg_time(r["Duration_Sec"])
        t_thumb = seconds_to_ffmpeg_time(r["Thumbnail_Frame_Sec"])

        in_vid = f"raw_videos/episode_{ep}.mp4"
        out_clip = f"clips/promo_ep{ep}_{int(r['Exact_Start_Sec'])}s_to_{int(r['Exact_End_Sec'])}s.mp4"
        out_thumb = f"thumbnails/thumb_ep{ep}_{int(r['Thumbnail_Frame_Sec'])}s.jpg"

        bat_lines.append(f'rem --- Episode {ep} Promo & Thumbnail ---')
        bat_lines.append(f'ffmpeg -y -ss {t_start} -i "{in_vid}" -t {t_dur} -c:v libx264 -crf 18 -preset fast -c:a aac "{out_clip}"')
        bat_lines.append(f'ffmpeg -y -ss {t_thumb} -i "{in_vid}" -vframes 1 -q:v 2 "{out_thumb}"\n')

    bat_path = os.path.join(output_dir, "slice_promos.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\n".join(bat_lines))
    logger.info("[SUCCESS] Generated FFmpeg slicing & thumbnail batch script -> %s", bat_path)

    print("\n" + "="*80)
    print("PROMOTIONAL MARKETING CAMPAIGN MANIFEST (SAMPLE):")
    print("="*80)
    print(campaign_df[["Episode", "Duration_Sec", "On_Screen_Hook_1", "Social_Caption"]].to_string())


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_pipeline(episodes_count=count)
