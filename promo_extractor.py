"""
Line-ID Anchored Promo Extractor & Cold Viewer Auditor
======================================================
1. Line-ID Anchoring: Numbers every line in an episode (e.g. E12-L034) so the LLM
   selects promo boundaries via start_line_id and end_line_id.
2. Code-level Timestamp Resolution: Converts Line IDs into exact timestamps and
   strictly validates duration (20-60s). Never trusts LLM timestamps.
3. Deterministic Quality Checks: Check_Hook, Check_Start, Check_End, Check_Context.
4. Cold Viewer Pass: Evaluates whether a viewer who never saw the show understands
   who/what/why from the isolated transcript snippet.
"""

import os
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd

from llm_client import generate_json
from deterministic_checks import run_all_deterministic_checks, resolve_segments_and_duration
from script_parser import episode_number

logger = logging.getLogger("PromoExtractor")

# Candidate extraction schema (up to 3 candidate promos per episode)
CANDIDATE_EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "candidate_promos": {
            "type": "ARRAY",
            "description": "Up to 3 high-tension promotional clips strictly between 20s and 60s total duration",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "segments": {
                        "type": "ARRAY",
                        "description": "List of ordered segments making up this promo (usually 1 continuous segment, or 2 non-contiguous jump-cuts)",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start_line_id": {"type": "STRING", "description": "e.g. E1-L005"},
                                "end_line_id": {"type": "STRING", "description": "e.g. E1-L028"}
                            },
                            "required": ["start_line_id", "end_line_id"]
                        }
                    },
                    "hook_score": {"type": "INTEGER", "description": "1 to 10 rating of opening 3s hook tension"},
                    "cliffhanger_score": {"type": "INTEGER", "description": "1 to 10 rating of closing cliffhanger urgency"},
                    "standalone_score": {"type": "INTEGER", "description": "1 to 10 rating of standalone clarity"},
                    "hook": {"type": "STRING", "description": "1-2 sentence description of the opening dramatic hook"},
                    "cliffhanger": {"type": "STRING", "description": "1-2 sentence description of the ending cliffhanger"},
                    "why": {"type": "STRING", "description": "One line explaining why this clip will stop thumbs and convert viewers"}
                },
                "required": [
                    "segments", "hook_score", "cliffhanger_score",
                    "standalone_score", "hook", "cliffhanger", "why"
                ]
            }
        }
    },
    "required": ["candidate_promos"]
}

COLD_VIEWER_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "pass": {"type": "BOOLEAN", "description": "true if a cold viewer understands the stakes, false otherwise"},
        "reason": {"type": "STRING", "description": "One sentence explaining why it is clear or confusing to a new viewer"}
    },
    "required": ["pass", "reason"]
}


def seconds_to_timecode(seconds: float) -> str:
    """Converts float seconds into MM:SS.ms formatted string."""
    if pd.isna(seconds) or seconds < 0:
        return "00:00.00"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:05.2f}"


def adjust_segments_to_duration(
    segments: List[Dict[str, str]],
    master_df: pd.DataFrame,
    min_dur: float = 20.0,
    max_dur: float = 60.0
) -> List[Dict[str, str]]:
    """
    Intelligently adjusts line boundaries forward or backward if an LLM candidate's
    selected line range is slightly under min_dur or over max_dur.
    """
    if not segments or "Line_ID" not in master_df.columns:
        return segments

    line_ids = list(master_df["Line_ID"])
    line_map = master_df.set_index("Line_ID")

    adjusted = [dict(s) for s in segments]
    last_seg = adjusted[-1]
    start_id = str(last_seg.get("start_line_id", "")).strip()
    end_id = str(last_seg.get("end_line_id", "")).strip()

    if start_id not in line_map.index or end_id not in line_map.index:
        return segments

    try:
        start_idx = line_ids.index(start_id)
        end_idx = line_ids.index(end_id)
    except ValueError:
        return segments

    is_valid, cur_dur, _, _ = resolve_segments_and_duration(adjusted, master_df, min_dur, max_dur)
    if is_valid:
        return adjusted

    # If too short: expand end_id forward line by line (staying within same episode)
    if cur_dur < min_dur:
        start_ep_row = line_map.loc[start_id]
        if isinstance(start_ep_row, pd.DataFrame):
            start_ep_row = start_ep_row.iloc[0]
        ep_val = int(start_ep_row["Episode"])

        while cur_dur < min_dur and end_idx + 1 < len(line_ids):
            next_line_id = line_ids[end_idx + 1]
            next_row = line_map.loc[next_line_id]
            if isinstance(next_row, pd.DataFrame):
                next_row = next_row.iloc[0]
            if int(next_row["Episode"]) != ep_val:
                break
            end_idx += 1
            last_seg["end_line_id"] = next_line_id
            _, cur_dur, _, _ = resolve_segments_and_duration(adjusted, master_df, 0.0, 999.0)
            if cur_dur > max_dur:
                end_idx -= 1
                last_seg["end_line_id"] = line_ids[end_idx]
                break

    # If too long: contract end_id backward line by line
    elif cur_dur > max_dur:
        while cur_dur > max_dur and end_idx > start_idx + 1:
            end_idx -= 1
            last_seg["end_line_id"] = line_ids[end_idx]
            _, cur_dur, _, _ = resolve_segments_and_duration(adjusted, master_df, 0.0, 999.0)

    return adjusted


def format_numbered_script(episode_df: pd.DataFrame) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Formats an episode's screenplay lines into a numbered transcript
    with line IDs (e.g. [E1-L001]) for unambiguous LLM anchoring.
    """
    lines_formatted = []
    logline = None
    continuity = None

    if "Episode_Logline" in episode_df.columns:
        valid_logs = episode_df["Episode_Logline"].dropna().unique()
        if len(valid_logs) > 0:
            logline = str(valid_logs[0])

    if "Continuity_Notes" in episode_df.columns:
        valid_notes = episode_df["Continuity_Notes"].dropna().unique()
        if len(valid_notes) > 0:
            continuity = str(valid_notes[0])

    for _, row in episode_df.iterrows():
        lid = str(row.get("Line_ID", f"E{row.get('Episode', 1)}-L{row.name:03d}"))
        t_start = seconds_to_timecode(float(row.get("Start_Sec", 0.0)))
        t_end = seconds_to_timecode(float(row.get("End_Sec", 0.0)))
        entity = str(row.get("Entity_Type", "ACTION"))
        emotion = f" ({row.get('Emotion')})" if pd.notna(row.get("Emotion")) and row.get("Emotion") else ""
        content = str(row.get("Content", "")).strip()

        lines_formatted.append(f"[{lid}] ({t_start} - {t_end}) {entity}{emotion}: {content}")

    return "\n".join(lines_formatted), logline, continuity


def _extract_promos_offline_heuristic(episode_df: pd.DataFrame, ep_num: int) -> List[Dict[str, Any]]:
    """
    Offline fallback: Generates line-ID anchored promotional candidates deterministically
    when no LLM API key is configured or during offline testing.
    """
    non_dialogue = {"CAMERA", "SOUND FX", "MUSIC", "SFX"}
    records = episode_df.reset_index(drop=True)
    num_r = len(records)
    candidates = []

    for i in range(num_r):
        row_i = records.loc[i]
        ent_i = str(row_i.get("Entity_Type", "")).upper()
        if ent_i in non_dialogue or ent_i == "ACTION":
            continue

        c_i = str(row_i.get("Content", "")).lstrip('"\'').strip()
        if c_i.startswith("...") or (len(c_i) > 0 and c_i[0].islower()):
            continue

        s_time = float(row_i["Start_Sec"])

        for j in range(i + 1, num_r):
            row_j = records.loc[j]
            e_time = float(row_j["End_Sec"])
            dur = e_time - s_time

            if dur > 58.0:
                break

            if dur >= 25.0:
                window = records.loc[i:j]
                dialogue_count = (~window["Entity_Type"].str.upper().isin(non_dialogue)).sum()
                has_emotion = window["Emotion"].dropna().count()
                score = (dialogue_count * 2.0) + (has_emotion * 1.5) - abs(dur - 38.0) * 0.2

                candidates.append({
                    "start_line_id": row_i["Line_ID"],
                    "end_line_id": row_j["Line_ID"],
                    "score": score,
                    "start_row": row_i,
                    "end_row": row_j,
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:3]

    results = []
    for c in top_candidates:
        results.append({
            "segments": [{"start_line_id": c["start_line_id"], "end_line_id": c["end_line_id"]}],
            "hook_score": float("nan"),
            "cliffhanger_score": float("nan"),
            "standalone_score": float("nan"),
            "hook": "heuristic window, no LLM description",
            "cliffhanger": "heuristic window, no LLM description",
            "why": "heuristic window, no LLM description"
        })

    return results


def extract_promos_for_episode(
    episode_df: pd.DataFrame,
    master_df: pd.DataFrame,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    allow_offline: bool = False,
    failures_log: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Extracts up to 3 candidate promotional clips for a single episode using line-ID anchoring,
    validates 20-60s duration, runs deterministic checks, and executes cold-viewer review.
    """
    if episode_df.empty:
        return []

    ep_num = int(episode_df.iloc[0].get("Episode", 1))
    target_model = model or os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL") or "gemini-3.5-flash-lite"
    script_text, logline, continuity = format_numbered_script(episode_df)

    prompt = f"""You are an elite short-form vertical video ad editor (Kuku, ReelShort, TikTok).
Your goal is to extract UP TO 3 candidate promotional clips from Episode {ep_num}.

### CRITICAL RULES:
1. ANCHOR BY LINE ID ONLY: Do not write timestamps. Specify clip boundaries using start_line_id and end_line_id from the bracketed IDs (e.g. 'E{ep_num}-L005').
2. STRICT DURATION (20.0s to 60.0s): The sum of duration of your segments MUST be between 20.0 and 60.0 seconds. Look at the (MM:SS - MM:SS) timestamps next to each line to calculate duration!
3. OPENING HOOK: The first line must hook the viewer immediately (confrontation, betrayal, slap, reveal, high drama). No lines starting with '...' or lowercase.
4. CLIFFHANGER: Cut off at peak dramatic tension before resolution.
5. STANDALONE CONTINUITY: A new viewer must understand the stakes without prior episodes.

### EPISODE CONTEXT:
- Episode Logline: {logline or 'N/A'}
- Continuity Notes: {continuity or 'N/A'}

### NUMBERED SCREENPLAY TRANSCRIPT:
{script_text}

Extract up to 3 high-impact promotional candidates. Return strictly JSON matching the schema.
"""

    system_instruction = "You are an expert microdrama promotional video editor. Output valid JSON matching the schema."

    response = None
    last_err = None
    last_dur_feedback = ""

    for attempt in range(2):
        try:
            curr_prompt = prompt
            if attempt == 1 and last_dur_feedback:
                curr_prompt += f"\n\n### CRITICAL DURATION RETRY ERROR:\n{last_dur_feedback}\nYou MUST adjust start_line_id and end_line_id so the total duration is strictly between 20.0 and 60.0 seconds!"

            response = generate_json(
                prompt=curr_prompt,
                schema=CANDIDATE_EXTRACTION_SCHEMA,
                system_instruction=system_instruction,
                api_key=api_key,
                provider=provider,
                model=target_model,
                temperature=0.2,
            )
            if response and "candidate_promos" in response:
                cands_test = response.get("candidate_promos", [])
                has_valid = False
                dur_errs = []
                for c_idx, cand in enumerate(cands_test, 1):
                    raw_s = cand.get("segments", [])
                    adj_s = adjust_segments_to_duration(raw_s, master_df)
                    is_ok, dur_val, _, msg = resolve_segments_and_duration(adj_s, master_df)
                    if is_ok:
                        has_valid = True
                        cand["segments"] = adj_s
                    else:
                        dur_errs.append(f"Candidate {c_idx} was {dur_val:.1f}s ({msg})")

                if has_valid:
                    break
                else:
                    last_dur_feedback = "Your candidate clips were outside 20-60s: " + "; ".join(dur_errs)
                    logger.warning("Episode %d attempt %d: all candidates violated duration: %s", ep_num, attempt + 1, last_dur_feedback)
        except Exception as e:
            last_err = e
            logger.warning("Episode %d candidate extraction attempt %d failed: %s", ep_num, attempt + 1, e)

    is_heuristic = False
    candidates_raw = []
    if response and "candidate_promos" in response:
        candidates_raw = response.get("candidate_promos", [])

    # If no LLM candidates passed duration after retry
    valid_llm_candidates = []
    for cand in candidates_raw:
        segs = adjust_segments_to_duration(cand.get("segments", []), master_df)
        is_ok, _, _, _ = resolve_segments_and_duration(segs, master_df)
        if is_ok:
            cand["segments"] = segs
            valid_llm_candidates.append(cand)

    if not valid_llm_candidates:
        if not allow_offline:
            err_msg = f"Episode {ep_num}: LLM extraction returned 0 valid 20-60s candidates ({last_dur_feedback or last_err or 'No response'}). Pass --allow_offline to permit heuristic runs."
            if failures_log is not None:
                failures_log.append({"Episode": ep_num, "Reason": err_msg})
            raise RuntimeError(err_msg)

        logger.info("Running deterministic heuristic candidate generation for Episode %d (allow_offline=True)...", ep_num)
        candidates_raw = _extract_promos_offline_heuristic(episode_df, ep_num)
        is_heuristic = True
    else:
        candidates_raw = valid_llm_candidates

    source_label = "HEURISTIC_NO_LLM" if is_heuristic else f"LLM:{target_model}"
    valid_candidates = []

    for c_idx, cand in enumerate(candidates_raw, 1):
        segs = cand.get("segments", [])
        is_valid_dur, total_dur, resolved_segs, dur_msg = resolve_segments_and_duration(
            segs, master_df, min_dur=20.0, max_dur=60.0
        )

        if not is_valid_dur:
            logger.warning("Episode %d Candidate %d duration rejected: %s", ep_num, c_idx, dur_msg)
            if failures_log is not None:
                failures_log.append({
                    "Episode": ep_num,
                    "Candidate_Idx": c_idx,
                    "Reason": f"Duration validation failed: {dur_msg}"
                })
            continue

        # Extract lines for deterministic checks & cold viewer
        start_line_id = resolved_segs[0]["start_line_id"]
        end_line_id = resolved_segs[-1]["end_line_id"]
        start_time_sec = resolved_segs[0]["start_sec"]
        end_time_sec = resolved_segs[-1]["end_sec"]

        # Collect all rows between the start and end of segments
        clip_line_dfs = []
        for r_seg in resolved_segs:
            seg_mask = (
                (master_df["Episode"] >= r_seg["episode_start"]) &
                (master_df["Episode"] <= r_seg["episode_end"]) &
                (master_df["Start_Sec"] >= r_seg["start_sec"] - 0.05) &
                (master_df["End_Sec"] <= r_seg["end_sec"] + 0.05)
            )
            clip_line_dfs.append(master_df[seg_mask])

        clip_lines = pd.concat(clip_line_dfs, ignore_index=True) if clip_line_dfs else pd.DataFrame()

        # Run deterministic checks
        det_checks = run_all_deterministic_checks(clip_lines, start_time_sec)

        # Build transcript snippet for cold viewer
        snippet_lines = []
        for _, row in clip_lines.iterrows():
            snippet_lines.append(f"{row.get('Entity_Type', 'ACTION')}: {row.get('Content', '')}")
        transcript_snippet = "\n".join(snippet_lines)

        # Cold Viewer Pass
        if is_heuristic:
            cold_status = "UNKNOWN"
            cold_reason = "Cold viewer audit not run in offline heuristic mode."
        else:
            cold_status, cold_reason = run_cold_viewer_audit(
                transcript_snippet=transcript_snippet,
                api_key=api_key,
                provider=provider,
                model=target_model
            )

        # Build formatted segment timestamps string
        seg_str_parts = []
        for s in resolved_segs:
            seg_str_parts.append(
                f"[E{s['episode_start']}: {seconds_to_timecode(s['start_sec'])} -> {seconds_to_timecode(s['end_sec'])} ({s['duration_sec']:.1f}s)]"
            )
        segments_summary = "; ".join(seg_str_parts)

        valid_candidates.append({
            "Source": source_label,
            "Episode": ep_num,
            "Start_Time": seconds_to_timecode(start_time_sec),
            "End_Time": seconds_to_timecode(end_time_sec),
            "Start_Sec": start_time_sec,
            "End_Sec": end_time_sec,
            "Duration_Sec": total_dur,
            "Segments_Count": len(resolved_segs),
            "Segments_Detail": segments_summary,
            "Start_Line_ID": start_line_id,
            "End_Line_ID": end_line_id,
            "Hook_Description": cand.get("hook", ""),
            "Cliffhanger_Description": cand.get("cliffhanger", ""),
            "Justification": cand.get("why", ""),
            "hook_score": cand.get("hook_score"),
            "cliffhanger_score": cand.get("cliffhanger_score"),
            "standalone_score": cand.get("standalone_score"),
            "Check_Hook": det_checks["Check_Hook"],
            "Check_Start": det_checks["Check_Start"],
            "Check_End": det_checks["Check_End"],
            "Check_Context": det_checks["Check_Context"],
            "All_Checks_Passed": det_checks["All_Checks_Passed"],
            "Cold_Viewer_Pass": cold_status,
            "Cold_Viewer_Reason": cold_reason,
            "raw_segments": resolved_segs,
        })

    return valid_candidates


def run_cold_viewer_audit(
    transcript_snippet: str,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Second LLM pass: Audits whether a viewer who never saw the show
    understands who is speaking, what the central conflict is, and why it matters.
    Returns (status, reason), where status is 'PASS', 'FAIL', or 'UNKNOWN' on error.
    """
    prompt = f"""You are a first-time viewer scrolling social media (TikTok/Reels/Shorts).
You have NEVER watched this show before. Read ONLY this raw audio-visual clip transcript:

{transcript_snippet}

Question: Does a first-time viewer immediately understand who the key characters are, what the conflict is, and why they should care?
If crucial context is completely missing (e.g. unknown names with no clue who they are, confusing unanchored dialogue), answer pass: false.
If the dramatic stakes and conflict are clear on their own, answer pass: true.

Return strictly JSON matching schema:
{{"pass": true/false, "reason": "one concise sentence explaining why"}}
"""

    try:
        res = generate_json(
            prompt=prompt,
            schema=COLD_VIEWER_SCHEMA,
            system_instruction="You are a cold viewer auditing video ad clarity. Output valid JSON.",
            api_key=api_key,
            provider=provider,
            model=model,
            temperature=0.1
        )
        passed = bool(res.get("pass", True))
        return ("PASS" if passed else "FAIL"), str(res.get("reason", "Clear standalone tension."))
    except Exception as e:
        logger.warning("Cold viewer audit failed: %s", e)
        return "UNKNOWN", f"Cold viewer audit unavailable ({e})"
    prompt = f"""You are a first-time viewer scrolling social media (TikTok/Reels/Shorts).
You have NEVER watched this show before. Read ONLY this raw audio-visual clip transcript:

{transcript_snippet}

Question: Does a first-time viewer immediately understand who the key characters are, what the conflict is, and why they should care?
If crucial context is completely missing (e.g. unknown names with no clue who they are, confusing unanchored dialogue), answer pass: false.
If the dramatic stakes and conflict are clear on their own, answer pass: true.

Return strictly JSON matching schema:
{{"pass": true/false, "reason": "one concise sentence explaining why"}}
"""

    try:
        res = generate_json(
            prompt=prompt,
            schema=COLD_VIEWER_SCHEMA,
            system_instruction="You are a cold viewer auditing video ad clarity. Output valid JSON.",
            api_key=api_key,
            provider=provider,
            model=model,
            temperature=0.1
        )
        return bool(res.get("pass", True)), str(res.get("reason", "Clear standalone tension."))
    except Exception as e:
        logger.warning("Cold viewer audit failed: %s", e)
        return True, "Cold viewer audit skipped due to API error."
