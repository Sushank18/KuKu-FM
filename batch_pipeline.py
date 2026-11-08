"""
Batch Processing Pipeline for Microdrama Scripts
------------------------------------------------
Ingests raw screenplay .txt files, executes deterministic parsing,
extracts 20-to-60-second candidate promotional windows, and generates
export files and sample LLM prompts.
"""

import os
import sys
import argparse
import pandas as pd
from script_parser import parse_screenplay
from clip_extractor import extract_candidate_windows, score_and_rank_candidates, format_llm_payload


def process_all_episodes(
    input_dir: str, 
    output_dir: str = "output",
    min_dur: float = 20.0,
    max_dur: float = 60.0
):
    os.makedirs(output_dir, exist_ok=True)
    
    txt_files = []
    for root, _, files in os.walk(input_dir):
        for f in files:
            if f.endswith(".txt"):
                txt_files.append(os.path.join(root, f))
    
    txt_files = sorted(txt_files)
    print(f"Found {len(txt_files)} screenplay text files in: {input_dir}")

    all_screenplay_dfs = []
    for idx, fpath in enumerate(txt_files, 1):
        fname = os.path.basename(fpath)
        try:
            df = parse_screenplay(fpath, include_extended_metadata=True)
            if not df.empty:
                df["Source_File"] = fname
                all_screenplay_dfs.append(df)
                print(f"  [{idx:02d}/{len(txt_files):02d}] {fname} -> {len(df)} lines parsed")
        except Exception as e:
            print(f"  [ERROR] Failed to parse {fname}: {e}", file=sys.stderr)

    if not all_screenplay_dfs:
        print("No screenplay lines were parsed. Check directory path.")
        return

    # 1. Combine into master screenplay DataFrame
    master_df = pd.concat(all_screenplay_dfs, ignore_index=True)
    master_csv = os.path.join(output_dir, "master_parsed_screenplays.csv")
    master_df.to_csv(master_csv, index=False)
    print(f"\n[OK] Master screenplay DataFrame saved: {master_csv} ({len(master_df)} total lines)")

    # 2. Extract strictly 20-60s candidate promotional clips
    print(f"\nExtracting promotional candidate windows ({min_dur}s to {max_dur}s)...")
    candidates_df = extract_candidate_windows(
        master_df,
        min_duration=min_dur,
        max_duration=max_dur,
        min_dialogue_lines=2
    )

    candidates_csv = os.path.join(output_dir, "candidate_promo_clips_20_60s.csv")
    candidates_df.to_csv(candidates_csv, index=False)
    print(f"[OK] Generated {len(candidates_df)} candidate clip windows -> Saved to: {candidates_csv}")

    # 3. Score and rank top candidates
    top_candidates = score_and_rank_candidates(candidates_df, top_k=10)
    top_candidates_csv = os.path.join(output_dir, "top_ranked_clips.csv")
    top_candidates.to_csv(top_candidates_csv, index=False)
    print(f"[OK] Top {len(top_candidates)} highest scoring clips -> Saved to: {top_candidates_csv}")

    # 4. Generate sample LLM prompt file for the #1 top-ranked candidate
    if not top_candidates.empty:
        sample_payload = format_llm_payload(master_df, top_candidates.iloc[0])
        sample_prompt_path = os.path.join(output_dir, "sample_llm_prompt.txt")
        with open(sample_prompt_path, "w", encoding="utf-8") as f:
            f.write(sample_payload["llm_prompt"])
        print(f"[OK] Generated sample LLM prompt for top clip -> Saved to: {sample_prompt_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Microdrama Script Parser & Clip Extractor")
    parser.add_argument(
        "--input_dir", 
        type=str, 
        default=os.path.join("Data", "I Married a Broken Soldier. He was a Duke"),
        help="Path to folder containing screenplay .txt files"
    )
    parser.add_argument("--output_dir", type=str, default="output", help="Directory to save output files")
    parser.add_argument("--min_dur", type=float, default=20.0, help="Min clip duration (seconds)")
    parser.add_argument("--max_dur", type=float, default=60.0, help="Max clip duration (seconds)")

    args = parser.parse_args()
    process_all_episodes(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        min_dur=args.min_dur,
        max_dur=args.max_dur
    )

