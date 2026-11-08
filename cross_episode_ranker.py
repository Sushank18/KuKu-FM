"""
Cross-Episode Ranking & Deduplication Engine
============================================
After candidates are extracted across all episodes:
  1. Deduplicates candidate clips overlapping by >30% in time range within an episode.
  2. Runs an LLM Judge pass evaluating an explicit 5-point rubric:
     - Hook Strength (0-10)
     - Cliffhanger Urgency (0-10)
     - Standalone Clarity (0-10)
     - Emotional Intensity (0-10)
     - Novelty vs Other Candidates (0-10)
  3. Combines judge score with deterministic check penalties.
  4. Generates a one-line 'Why_Post_First' for top recommendations.
"""

import logging
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd

from llm_client import generate_json

logger = logging.getLogger("CrossEpisodeRanker")

JUDGE_RUBRIC_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "evaluations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "candidate_id": {"type": "STRING"},
                    "hook_strength": {"type": "INTEGER", "description": "0-10 rating"},
                    "cliffhanger": {"type": "INTEGER", "description": "0-10 rating"},
                    "standalone_clarity": {"type": "INTEGER", "description": "0-10 rating"},
                    "emotional_intensity": {"type": "INTEGER", "description": "0-10 rating"},
                    "novelty": {"type": "INTEGER", "description": "0-10 rating"},
                    "why_post_first": {"type": "STRING", "description": "One line explaining why this clip should lead the campaign"}
                },
                "required": [
                    "candidate_id", "hook_strength", "cliffhanger",
                    "standalone_clarity", "emotional_intensity", "novelty", "why_post_first"
                ]
            }
        }
    },
    "required": ["evaluations"]
}


def compute_clip_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    """Calculates temporal overlap ratio between two clips [0.0 to 1.0]."""
    dur_a = max(0.01, end_a - start_a)
    dur_b = max(0.01, end_b - start_b)

    overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    return overlap / min(dur_a, dur_b)


def deduplicate_overlapping_candidates(candidates: List[Dict[str, Any]], overlap_threshold: float = 0.30) -> List[Dict[str, Any]]:
    """
    Drops candidate clips that overlap another candidate within the same episode
    by >30% of their duration, keeping the candidate with higher initial score.
    """
    if len(candidates) <= 1:
        return candidates

    # Group by primary episode
    by_ep: Dict[int, List[Dict[str, Any]]] = {}
    for c in candidates:
        ep = c.get("Episode", 1)
        by_ep.setdefault(ep, []).append(c)

    deduped: List[Dict[str, Any]] = []

    for ep, ep_candidates in by_ep.items():
        # Sort by initial score descending
        def get_initial_score(item):
            return (
                item.get("hook_score", 5) * 3 +
                item.get("cliffhanger_score", 5) * 3 +
                item.get("standalone_score", 5) * 4
            )

        sorted_c = sorted(ep_candidates, key=get_initial_score, reverse=True)
        kept_for_ep: List[Dict[str, Any]] = []

        for candidate in sorted_c:
            c_start = candidate.get("Start_Sec", 0.0)
            c_end = candidate.get("End_Sec", 0.0)

            overlaps_existing = False
            for kept in kept_for_ep:
                k_start = kept.get("Start_Sec", 0.0)
                k_end = kept.get("End_Sec", 0.0)
                ov = compute_clip_overlap(c_start, c_end, k_start, k_end)
                if ov > overlap_threshold:
                    overlaps_existing = True
                    logger.info(
                        "Deduplicating candidate Ep %s [%.1fs-%.1fs]: overlaps [%.1fs-%.1fs] by %.1f%%",
                        ep, c_start, c_end, k_start, k_end, ov * 100
                    )
                    break

            if not overlaps_existing:
                kept_for_ep.append(candidate)

        deduped.extend(kept_for_ep)

    return deduped


def run_llm_judge_ranking(
    candidates: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Evaluates candidate clips with an explicit multi-dimensional rubric,
    applies deterministic check penalties, and sorts by Rank_Score.
    """
    if not candidates:
        return []

    # Assign temporary candidate_ids for judge prompt
    for idx, c in enumerate(candidates, 1):
        c["candidate_id"] = f"CAND_{idx:03d}"

    # Build prompt with candidate summaries
    prompt_lines = [
        "You are an executive media buyer and creative strategist for top vertical microdrama apps (Kuku, ReelShort).",
        "Evaluate the following promotional candidate clips using this explicit 0-10 rubric:",
        "  1. hook_strength (0-10): Stop-rate in first 3 seconds (betrayal, slap, shock reveal, confrontation).",
        "  2. cliffhanger (0-10): Curiosity gap at the cut (unanswered question, life-or-death decision).",
        "  3. standalone_clarity (0-10): Can a new viewer immediately grasp the conflict without prior episodes?",
        "  4. emotional_intensity (0-10): Visceral viewer reaction (rage, injustice, heartbreak, thrill).",
        "  5. novelty (0-10): Fresh dramatic angle compared to standard tropes.",
        "Provide why_post_first (a punchy 1-sentence rationale for marketing).",
        "",
        "### CANDIDATE CLIPS:"
    ]

    for c in candidates:
        prompt_lines.append(
            f"ID: {c['candidate_id']} | Episode: {c.get('Episode')} | Duration: {c.get('Duration_Sec', 0):.1f}s\n"
            f"  Opening Hook: {c.get('Hook_Description')}\n"
            f"  Ending Cliffhanger: {c.get('Cliffhanger_Description')}\n"
            f"  Why it works: {c.get('Justification')}\n"
            f"  Transcript: {c.get('Transcript_Snippet', '')[:250]}\n"
        )

    prompt = "\n".join(prompt_lines)

    judge_results: Dict[str, Dict[str, Any]] = {}
    try:
        response = generate_json(
            prompt=prompt,
            schema=JUDGE_RUBRIC_SCHEMA,
            system_instruction="You are an expert microdrama ad ranking judge. Output strictly valid JSON matching schema.",
            api_key=api_key,
            provider=provider,
            model=model,
            temperature=0.2
        )
        evals = response.get("evaluations", [])
        for ev in evals:
            cid = ev.get("candidate_id")
            if cid:
                judge_results[cid] = ev
    except Exception as e:
        logger.warning("LLM Judge call failed (%s). Falling back to heuristic scoring.", e)

    # Score each candidate
    ranked_list = []
    for c in candidates:
        cid = c.get("candidate_id", "")
        j_eval = judge_results.get(cid, {})

        hook_s = j_eval.get("hook_strength", c.get("hook_score", 7))
        cliff_s = j_eval.get("cliffhanger", c.get("cliffhanger_score", 7))
        clarity_s = j_eval.get("standalone_clarity", c.get("standalone_score", 7))
        intense_s = j_eval.get("emotional_intensity", 7)
        nov_s = j_eval.get("novelty", 7)
        why_first = j_eval.get("why_post_first", c.get("Justification", "Strong dramatic hook with standalone appeal."))

        # Base rubric calculation (0-100)
        base_score = (
            hook_s * 2.5 +
            cliff_s * 2.5 +
            clarity_s * 2.0 +
            intense_s * 2.0 +
            nov_s * 1.0
        )

        # Apply deterministic check penalties
        penalties = 0.0
        if "FAIL" in str(c.get("Check_Hook", "")):
            penalties += 15.0
        if "FAIL" in str(c.get("Check_Start", "")):
            penalties += 20.0
        if "FAIL" in str(c.get("Check_End", "")):
            penalties += 15.0
        if "needs_context" in str(c.get("Check_Context", "")):
            penalties += 10.0
        if str(c.get("Cold_Viewer_Pass", "")).upper() == "FAIL":
            penalties += 10.0

        final_score = round(max(0.0, min(100.0, base_score - penalties)), 1)

        c["Rank_Score"] = final_score
        c["Why_Post_First"] = why_first
        c["Judge_Hook"] = hook_s
        c["Judge_Cliffhanger"] = cliff_s
        c["Judge_Clarity"] = clarity_s
        c["Judge_Intensity"] = intense_s
        c["Judge_Novelty"] = nov_s
        ranked_list.append(c)

    # Sort descending by Rank_Score
    ranked_list.sort(key=lambda x: x["Rank_Score"], reverse=True)

    # Assign integer Rank (1, 2, 3...)
    for rank_idx, item in enumerate(ranked_list, 1):
        item["Rank"] = rank_idx

    return ranked_list
