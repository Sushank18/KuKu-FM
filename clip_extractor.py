"""
Promotional Clip Extractor for Microdramas
-------------------------------------------
Calculates strict 20-to-60-second contiguous candidate windows within scenes,
scores candidates on hook potential and dialogue density, and formats
structured LLM prompts.
"""

from typing import List, Dict, Any, Optional
import pandas as pd


def extract_candidate_windows(
    df: pd.DataFrame,
    min_duration: float = 20.0,
    max_duration: float = 60.0,
    min_dialogue_lines: int = 2,
    disallow_mid_scene_start: bool = False,
) -> pd.DataFrame:
    """
    Finds contiguous sequences of dialogue and action within each scene
    that fall strictly within [min_duration, max_duration] seconds.

    Filters candidates requiring at least `min_dialogue_lines` of spoken character dialogue.
    """
    candidates: List[Dict[str, Any]] = []

    # Non-character entities
    system_entities = {"CAMERA", "ACTION", "SOUND FX", "MUSIC", "SFX"}

    # Group by episode and scene to ensure clips do not cross scene boundaries
    group_keys = [col for col in ["Episode", "Scene"] if col in df.columns]
    if not group_keys:
        grouped = [(None, df)]
    else:
        grouped = df.groupby(group_keys, sort=False)

    for group_val, scene_df in grouped:
        records = scene_df.reset_index(drop=True)
        num_records = len(records)

        ep = records.loc[0, "Episode"] if "Episode" in records.columns else None
        sc = records.loc[0, "Scene"] if "Scene" in records.columns else None
        sc_heading = records.loc[0, "Scene_Heading"] if "Scene_Heading" in records.columns else None
        ep_logline = records.loc[0, "Episode_Logline"] if "Episode_Logline" in records.columns else None

        for start_i in range(num_records):
            start_time = records.loc[start_i, "Start_Sec"]
            start_entity = records.loc[start_i, "Entity_Type"]

            for end_i in range(start_i, num_records):
                end_time = records.loc[end_i, "End_Sec"]
                clip_dur = round(end_time - start_time, 2)

                # Strict boundary enforcement
                if clip_dur > max_duration:
                    break

                if clip_dur >= min_duration:
                    window = records.loc[start_i:end_i]
                    
                    # Dialogue vs. Non-dialogue
                    dialogue_mask = ~window["Entity_Type"].str.upper().isin(system_entities)
                    dialogue_lines = int(dialogue_mask.sum())

                    if dialogue_lines >= min_dialogue_lines:
                        # Extract emotions and characters
                        characters = window.loc[dialogue_mask, "Entity_Type"].unique().tolist()
                        emotions = window["Emotion"].dropna().unique().tolist()

                        candidates.append({
                            "Episode": ep,
                            "Scene": sc,
                            "Scene_Heading": sc_heading,
                            "Episode_Logline": ep_logline,
                            "Start_Line_Idx": int(records.loc[start_i, "Line_Index"]) if "Line_Index" in records.columns else start_i,
                            "End_Line_Idx": int(records.loc[end_i, "Line_Index"]) if "Line_Index" in records.columns else end_i,
                            "Clip_Start_Sec": start_time,
                            "Clip_End_Sec": end_time,
                            "Duration_Sec": clip_dur,
                            "Total_Lines": end_i - start_i + 1,
                            "Dialogue_Lines": dialogue_lines,
                            "Characters": ", ".join(characters),
                            "Key_Emotions": ", ".join(emotions) if emotions else "None",
                            "Opening_Hook": f"[{start_entity}]: {str(records.loc[start_i, 'Content'])[:80]}",
                            "Closing_Cliffhanger": f"[{records.loc[end_i, 'Entity_Type']}]: {str(records.loc[end_i, 'Content'])[:80]}",
                        })

    return pd.DataFrame(candidates)


def score_and_rank_candidates(candidates_df: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    """
    Ranks candidate clips using heuristic signals optimal for vertical microdrama ads:
    - High dialogue line count
    - High emotional intensity (count of emotion tags)
    - Optimal duration (sweet spot ~ 30-45s)
    """
    if candidates_df.empty:
        return candidates_df

    scored = candidates_df.copy()
    
    # 1. Sweet spot bonus (30-45s is optimal for vertical microdrama ads)
    duration_scores = 1.0 - (scored["Duration_Sec"] - 38.0).abs() / 38.0
    
    # 2. Dialogue density score
    dialogue_density = scored["Dialogue_Lines"] / scored["Total_Lines"]

    # 3. Emotion presence score
    emotion_count = scored["Key_Emotions"].apply(
        lambda e: 0 if e == "None" else len(e.split(","))
    )

    scored["Promo_Score"] = (
        duration_scores * 0.35 +
        dialogue_density * 0.35 +
        (emotion_count / (emotion_count.max() or 1)) * 0.30
    ).round(4)

    ranked = scored.sort_values(by="Promo_Score", ascending=False).reset_index(drop=True)
    return ranked.head(top_k)


def format_llm_payload(screenplay_df: pd.DataFrame, candidate_row: pd.Series) -> Dict[str, Any]:
    """
    Builds a structured dictionary payload and formatted prompt text
    ready to send to an LLM for final selection, clip rating, or ad copy generation.
    """
    # Slice rows corresponding to the candidate window
    start_sec = candidate_row["Clip_Start_Sec"]
    end_sec = candidate_row["Clip_End_Sec"]
    ep = candidate_row["Episode"]
    sc = candidate_row["Scene"]

    mask = (
        (screenplay_df["Episode"] == ep) &
        (screenplay_df["Scene"] == sc) &
        (screenplay_df["Start_Sec"] >= start_sec - 0.01) &
        (screenplay_df["End_Sec"] <= end_sec + 0.01)
    )
    window_lines = screenplay_df[mask]

    formatted_transcript = []
    for _, row in window_lines.iterrows():
        entity = row["Entity_Type"]
        emotion_str = f" ({row['Emotion']})" if pd.notna(row["Emotion"]) else ""
        t_start = f"{row['Start_Sec']:.2f}"
        t_end = f"{row['End_Sec']:.2f}"
        content = row["Content"]
        formatted_transcript.append(f"[{t_start}s - {t_end}s] {entity}{emotion_str}: {content}")

    transcript_text = "\n".join(formatted_transcript)

    prompt = f"""You are an elite short-form video editor for vertical microdramas (e.g., ReelShort, TikTok, Shorts).
Evaluate the following candidate clip window strictly measuring {candidate_row['Duration_Sec']:.2f} seconds.

### CLIP METADATA
- Episode: {ep}
- Scene: {sc} ({candidate_row.get('Scene_Heading', 'N/A')})
- Episode Logline: {candidate_row.get('Episode_Logline', 'N/A')}
- Timeframe: {start_sec:.2f}s to {end_sec:.2f}s (Total: {candidate_row['Duration_Sec']:.2f}s)
- Characters Involved: {candidate_row.get('Characters', 'N/A')}
- Key Emotions: {candidate_row.get('Key_Emotions', 'None')}

### SCREENPLAY TRANSCRIPT:
{transcript_text}

### TASKS:
1. Hook Rating (1-10): Rate how effectively the first 3 seconds hook the viewer.
2. Cliffhanger Rating (1-10): Rate if the ending leaves an urgent question/emotional cliffhanger.
3. Promotional Headline: Write 1 punchy 5-7 word on-screen hook caption.
4. Final Recommendation: [APPROVED / REJECTED] with a 1-sentence rationale.
"""
    return {
        "metadata": candidate_row.to_dict(),
        "transcript": transcript_text,
        "llm_prompt": prompt
    }

