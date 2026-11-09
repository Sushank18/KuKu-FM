"""
End-to-End Microdrama Promotional Clip Pipeline Runner
======================================================
Coordinates:
  1. Screenplay ingestion with Line-ID anchoring, loglines, and continuity notes.
  2. Line-ID anchored candidate promo extraction (up to 3 per episode).
  3. Deterministic code-level checks (Check_Hook, Check_Start, Check_End, Check_Context).
  4. Cold Viewer LLM audit pass.
  5. Cross-episode deduplication (>30% overlap) and LLM judge ranking rubric.
  6. Subtitle generation (.srt) and FFmpeg slicing command generation.
  7. Isolated outputs per run:
     - output/run_<YYYYMMDD_HHMMSS>/promos.csv
     - output/run_<YYYYMMDD_HHMMSS>/promos.json
     - output/run_<YYYYMMDD_HHMMSS>/failures.csv
     - output/run_<YYYYMMDD_HHMMSS>/run_log.txt
"""

import os
import sys
import time
import json
import shutil
import logging
import argparse
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd

from script_parser import parse_screenplay, episode_number
from llm_client import reset_run_stats, get_run_stats
from promo_extractor import extract_promos_for_episode
from cross_episode_ranker import deduplicate_overlapping_candidates, run_llm_judge_ranking
from phase3_video_pipeline import (
    generate_promo_srt,
    generate_ffmpeg_commands,
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
            start_ep = int(parts[0])
            end_ep = int(parts[1])
            return [e for e in sorted_eps if start_ep <= e <= end_ep]
        except ValueError:
            logger.warning("Could not parse episode range '%s'. Defaulting to all.", ep_arg)
            return sorted_eps

    try:
        count = int(ep_str)
        return sorted_eps[:count]
    except ValueError:
        logger.warning("Could not parse episode argument '%s'. Defaulting to all.", ep_arg)
        return sorted_eps


def run_pipeline(
    episodes: Optional[str] = None,
    output_dir: str = "output",
    master_csv: str = "output/master_parsed_screenplays.csv",
    scripts_dir: str = os.path.join("Data", "I Married a Broken Soldier. He was a Duke"),
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    allow_offline: bool = False,
    min_dur: float = 20.0,
    max_dur: float = 60.0
) -> Dict[str, Any]:
    """
    Main orchestration entry point:
      - Screenplay Ingestion
      - Line-ID Candidate Extraction (up to 3 / episode)
      - Deterministic Rule Checks (Hook, Start, End, Context)
      - Cold Viewer Pass
      - Cross-Episode Overlap Deduplication & Ranking Rubric
      - Viral Packaging & SRT Subtitle Generation
      - Raw Output Persistence (promos.csv, promos.json, failures.csv, run_log.txt)
    """
    start_time_real = time.time()
    reset_run_stats()

    # 1. Create timestamped run output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(output_dir, f"run_{timestamp}")
    subtitles_dir = os.path.join(run_dir, "subtitles")
    os.makedirs(subtitles_dir, exist_ok=True)

    failures_csv = os.path.join(run_dir, "failures.csv")
    failures_log: List[Dict[str, Any]] = []

    logger.info("=" * 70)
    logger.info("STARTING KUKU PROMOTIONAL CLIP PIPELINE RUN: %s", run_dir)
    logger.info("=" * 70)

    # 2. Ingest or parse screenplay lines
    screenplay_df = None
    if os.path.exists(master_csv):
        try:
            logger.info("Loading existing master screenplay CSV from %s...", master_csv)
            df_temp = pd.read_csv(master_csv)
            if "Line_ID" in df_temp.columns and not df_temp.empty:
                screenplay_df = df_temp
                logger.info("Loaded %d master lines with Line_ID from CSV.", len(screenplay_df))
        except Exception as e:
            logger.warning("Failed to load %s: %s", master_csv, e)

    if screenplay_df is None or screenplay_df.empty:
        logger.info("Parsing raw screenplay scripts from %s...", scripts_dir)
        if not os.path.exists(scripts_dir):
            raise FileNotFoundError(f"Scripts directory not found: {scripts_dir}")

        txt_files = [f for f in os.listdir(scripts_dir) if f.endswith(".txt")]
        txt_files.sort(key=lambda f: episode_number(f))
        logger.info("Discovered %d screenplay text files.", len(txt_files))

        all_dfs = []
        for f in txt_files:
            p = os.path.join(scripts_dir, f)
            parsed_df = parse_screenplay(p, include_extended_metadata=True)
            all_dfs.append(parsed_df)

        screenplay_df = pd.concat(all_dfs, ignore_index=True)
        os.makedirs(output_dir, exist_ok=True)
        screenplay_df.to_csv(master_csv, index=False)
        logger.info("Saved master screenplay CSV -> %s (%d lines)", master_csv, len(screenplay_df))

    # Ensure Episode column is integer
    screenplay_df["Episode"] = screenplay_df["Episode"].apply(episode_number).astype(int)

    # 3. Determine target episodes
    available_episodes = sorted(list(screenplay_df["Episode"].unique()))
    target_episodes = parse_episode_selection(episodes, available_episodes)
    logger.info(
        "Targeting %d of %d episodes: %s",
        len(target_episodes), len(available_episodes),
        target_episodes[:10] + (["..."] if len(target_episodes) > 10 else [])
    )

    # 4. Extract Line-ID anchored candidate promos across target episodes
    all_raw_candidates: List[Dict[str, Any]] = []

    for idx, ep_num in enumerate(target_episodes, 1):
        ep_mask = screenplay_df["Episode"] == ep_num
        episode_df = screenplay_df[ep_mask].copy().reset_index(drop=True)

        logger.info("[%d/%d] Extracting candidate promos for Episode %d...", idx, len(target_episodes), ep_num)
        ep_candidates = extract_promos_for_episode(
            episode_df=episode_df,
            master_df=screenplay_df,
            api_key=api_key,
            provider=provider,
            model=model,
            allow_offline=allow_offline,
            failures_log=failures_log
        )

        all_raw_candidates.extend(ep_candidates)
        time.sleep(0.5)  # API pacing

    logger.info("Total raw candidates extracted across episodes: %d", len(all_raw_candidates))

    # 5. Cross-episode deduplication (>30% overlap)
    logger.info("Executing cross-episode deduplication (>30% temporal overlap)...")
    deduped_candidates = deduplicate_overlapping_candidates(all_raw_candidates, overlap_threshold=0.30)
    logger.info("Retained %d candidates after deduplication.", len(deduped_candidates))

    # 6. Cross-episode ranking pass with explicit judge rubric & deterministic check penalties
    logger.info("Running cross-episode LLM Judge evaluation and check penalization...")
    ranked_candidates = run_llm_judge_ranking(
        candidates=deduped_candidates,
        api_key=api_key,
        provider=provider,
        model=model,
        allow_offline=allow_offline
    )

    # 7. Package viral marketing creatives & generate .srt subtitles
    final_records: List[Dict[str, Any]] = []

    for rank_idx, cand in enumerate(ranked_candidates, 1):
        ep_num = cand.get("Episode", 1)
        start_sec = cand.get("Start_Sec", 0.0)
        end_sec = cand.get("End_Sec", 30.0)
        is_heuristic = (cand.get("Source") == "HEURISTIC_NO_LLM")

        # Generate Subtitle file (.srt)
        srt_filename = f"promo_ep{ep_num}_{int(start_sec)}s_{int(end_sec)}s.srt"
        srt_path = os.path.join(subtitles_dir, srt_filename)

        generate_promo_srt(
            screenplay_df=screenplay_df,
            episode_id=ep_num,
            clip_start_sec=start_sec,
            clip_end_sec=end_sec,
            output_srt_path=srt_path,
            include_speaker_names=True
        )

        if is_heuristic:
            # Under --allow_offline heuristic, creatives are left strictly empty
            cand["Rank"] = rank_idx
            cand["On_Screen_Hook_1"] = ""
            cand["On_Screen_Hook_2"] = ""
            cand["On_Screen_Hook_3"] = ""
            cand["Social_Caption"] = ""
            cand["Hashtags"] = ""
            cand["Call_To_Action"] = ""
            cand["Thumbnail_Frame_Sec"] = start_sec + 2.0
            cand["SRT_Subtitle_Path"] = srt_path
        else:
            creatives = generate_marketing_creatives(
                episode_id=ep_num,
                hook_desc=cand.get("Hook_Description", ""),
                cliffhanger_desc=cand.get("Cliffhanger_Description", ""),
                transcript_text="",
                model_name=model,
                api_key=api_key,
                provider=provider
            )
            thumbnail_sec = calculate_optimal_thumbnail_timestamp(
                screenplay_df=screenplay_df,
                episode_id=ep_num,
                clip_start_sec=start_sec,
                clip_end_sec=end_sec
            )
            hook_opts = creatives.get("on_screen_hook_options", [])
            cand["Rank"] = rank_idx
            cand["On_Screen_Hook_1"] = hook_opts[0] if len(hook_opts) > 0 else ""
            cand["On_Screen_Hook_2"] = hook_opts[1] if len(hook_opts) > 1 else ""
            cand["On_Screen_Hook_3"] = hook_opts[2] if len(hook_opts) > 2 else ""
            cand["Social_Caption"] = creatives.get("social_caption", "")
            cand["Hashtags"] = " ".join(creatives.get("hashtags", []))
            cand["Call_To_Action"] = creatives.get("call_to_action", "")
            cand["Thumbnail_Frame_Sec"] = thumbnail_sec
            cand["SRT_Subtitle_Path"] = srt_path

        final_records.append(cand)

    # 8. Persist failures.csv
    if failures_log:
        pd.DataFrame(failures_log).to_csv(failures_csv, index=False)
    else:
        # Empty failures log
        pd.DataFrame(columns=["Episode", "Candidate_Idx", "Reason"]).to_csv(failures_csv, index=False)

    # 9. Persist promos.csv and promos.json (drop raw objects and transcript snippets)
    promos_df = pd.DataFrame(final_records)
    promos_csv = os.path.join(run_dir, "promos.csv")
    promos_json = os.path.join(run_dir, "promos.json")

    serializable_df = promos_df.drop(columns=["raw_segments", "Transcript_Snippet"], errors="ignore")
    serializable_df.to_csv(promos_csv, index=False)

    with open(promos_json, "w", encoding="utf-8") as f:
        json.dump(serializable_df.to_dict(orient="records"), f, indent=2)

    logger.info("[SUCCESS] Exported raw run files: %s and %s", promos_csv, promos_json)

    # Also update shared output/promo_campaign for the Streamlit dashboard
    shared_dir = os.path.join(output_dir, "promo_campaign")
    os.makedirs(shared_dir, exist_ok=True)
    shared_manifest_csv = os.path.join(shared_dir, "promo_campaign_manifest.csv")
    serializable_df.to_csv(shared_manifest_csv, index=False)

    # Copy subtitles into shared subtitles folder
    shared_subs = os.path.join(shared_dir, "subtitles")
    os.makedirs(shared_subs, exist_ok=True)
    if os.path.exists(subtitles_dir):
        for sfile in os.listdir(subtitles_dir):
            shutil.copy2(os.path.join(subtitles_dir, sfile), os.path.join(shared_subs, sfile))

    # Generate slice_promos.bat
    bat_commands = generate_ffmpeg_commands(
        promos_df=serializable_df,
        video_source_dir="raw_videos",
        output_dir="clips",
        script_type="bat"
    )
    bat_path = os.path.join(run_dir, "slice_promos.bat")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_commands)
    shutil.copy2(bat_path, os.path.join(shared_dir, "slice_promos.bat"))

    # 10. Persist run_log.txt
    elapsed_time = round(time.time() - start_time_real, 2)
    stats = get_run_stats()
    calls_made = stats.get("calls", 0)

    # Compute source counts
    source_counts = dict(serializable_df["Source"].value_counts()) if "Source" in serializable_df.columns else {}

    top_banner = "NO LLM CALLS - HEURISTIC MODE\n" if calls_made == 0 else ""

    run_log_content = f"""{top_banner}======================================================================
KUKU PROMO EXTRACTION PIPELINE EXECUTION LOG
======================================================================
Timestamp: {timestamp}
Run Directory: {run_dir}
Target Episodes: {len(target_episodes)}
Total Candidate Promos Generated: {len(final_records)}
Source Counts: {source_counts}
Execution Elapsed Time: {elapsed_time:.2f} seconds

LLM MODEL & USAGE STATISTICS:
Provider Used: {stats.get('provider_used') or (provider if calls_made > 0 else 'none')}
Model Used: {stats.get('model_used') or (model if calls_made > 0 else 'none')}
Total API Calls: {calls_made}
Prompt (Input) Tokens: {stats.get('input_tokens', 0):,}
Completion (Output) Tokens: {stats.get('output_tokens', 0):,}
Total Tokens: {stats.get('total_tokens', 0):,}
Estimated Cost (USD): ${stats.get('estimated_cost_usd', 0.0):.5f}

OUTPUT FILES CREATED:
  - {promos_csv}
  - {promos_json}
  - {failures_csv}
  - {bat_path}
======================================================================
"""
    run_log_path = os.path.join(run_dir, "run_log.txt")
    with open(run_log_path, "w", encoding="utf-8") as f:
        f.write(run_log_content)

    print("\n" + run_log_content)
    return {
        "run_dir": run_dir,
        "promos_csv": promos_csv,
        "promos_json": promos_json,
        "failures_csv": failures_csv,
        "run_log_path": run_log_path,
        "promos_df": serializable_df,
        "stats": stats,
        "elapsed_time": elapsed_time
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-End Microdrama Promotional Pipeline")
    parser.add_argument(
        "--episodes",
        type=str,
        default=None,
        help="Optional episode count (e.g. 5) or range (e.g. 1-10). Default: all episodes."
    )
    parser.add_argument("--output_dir", type=str, default="output", help="Base output directory")
    parser.add_argument("--master_csv", type=str, default="output/master_parsed_screenplays.csv")
    parser.add_argument(
        "--scripts_dir",
        type=str,
        default=os.path.join("Data", "I Married a Broken Soldier. He was a Duke")
    )
    parser.add_argument("--provider", type=str, default=None, help="gemini or openai")
    parser.add_argument("--model", type=str, default=None, help="LLM model name")
    parser.add_argument(
        "--allow_offline",
        action="store_true",
        default=False,
        help="Permit deterministic heuristic execution when no LLM API key is present."
    )

    args = parser.parse_args()
    run_pipeline(
        episodes=args.episodes,
        output_dir=args.output_dir,
        master_csv=args.master_csv,
        scripts_dir=args.scripts_dir,
        provider=args.provider,
        model=args.model,
        allow_offline=args.allow_offline
    )
