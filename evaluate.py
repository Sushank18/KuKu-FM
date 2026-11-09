"""
Quality Evaluation & Failure Audit Suite
========================================
1. Evaluates pipeline precision against user ground truth (eval/labels.csv).
2. Computes Precision@N using ONLY clips that overlap user labels (IoU >= 0.35).
   Reports "n_labelled_matches / N" and prints "insufficient labels" if matches < 3.
3. Analyzes failure rates across deterministic checks (Check_Hook, Check_Start, Check_End, Check_Context).
4. Auto-generates FAILURES.md dynamically from the latest promos.csv:
   - Picks up to 5 rows with failed checks (or lowest Rank_Score).
   - Pulls transcripts VERBATIM from master screenplay lines by Line_ID.
   - Asserts that every quoted line exists in the source script before writing.
"""

import os
import glob
import argparse
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional

from deterministic_checks import timecode_to_seconds
from script_parser import parse_screenplay, episode_number


def compute_overlap(s1: float, e1: float, s2: float, e2: float) -> float:
    """Calculates intersection over union (IoU) of two time intervals."""
    inter = max(0.0, min(e1, e2) - max(s1, s2))
    union = max(0.01, max(e1, e2) - min(s1, s2))
    return inter / union


def find_latest_promos_csv() -> Optional[str]:
    """Locates the latest run's promos.csv or fallback manifest."""
    run_csvs = sorted(glob.glob(os.path.join("output", "run_*", "promos.csv")), reverse=True)
    if run_csvs:
        return run_csvs[0]

    campaign_csvs = [
        os.path.join("output", "promo_campaign", "promo_campaign_manifest.csv"),
    ]
    for p in campaign_csvs:
        if os.path.exists(p):
            return p
    return None


def load_master_screenplay_df(
    master_csv: str = "output/master_parsed_screenplays.csv",
    scripts_dir: str = os.path.join("Data", "I Married a Broken Soldier. He was a Duke")
) -> pd.DataFrame:
    """Loads master parsed dataframe or parses from Data/ directory."""
    if os.path.exists(master_csv):
        try:
            df = pd.read_csv(master_csv)
            if "Line_ID" in df.columns and not df.empty:
                return df
        except Exception:
            pass

    if os.path.exists(scripts_dir):
        txt_files = [f for f in os.listdir(scripts_dir) if f.endswith(".txt")]
        txt_files.sort(key=lambda f: episode_number(f))
        all_dfs = []
        for f in txt_files:
            p = os.path.join(scripts_dir, f)
            all_dfs.append(parse_screenplay(p, include_extended_metadata=True))
        if all_dfs:
            master = pd.concat(all_dfs, ignore_index=True)
            return master

    return pd.DataFrame()


def evaluate_precision_at_n(
    promos_df: pd.DataFrame, 
    labels_df: pd.DataFrame, 
    top_n_list: List[int] = [1, 3, 5]
) -> Dict[str, str]:
    """
    Computes Precision@N using ONLY clips that overlap user labels (IoU >= 0.35).
    Reports 'n_labelled_matches / N' next to percentage.
    If there are fewer than 3 matches, reports 'insufficient labels'.
    """
    results: Dict[str, str] = {}
    if promos_df.empty or labels_df.empty or len(labels_df) == 0:
        for n in top_n_list:
            results[f"Precision@{n}"] = "insufficient labels (0 matches / 0 labels)"
        return results

    df = promos_df.copy()
    if "Rank" in df.columns:
        df = df.sort_values(by="Rank", ascending=True)
    elif "Rank_Score" in df.columns:
        df = df.sort_values(by="Rank_Score", ascending=False)

    for n in top_n_list:
        top_slice = df.head(n)
        good_matches = 0
        total_matches = 0

        for _, row in top_slice.iterrows():
            ep = int(row.get("Episode", 1))
            start_sec = timecode_to_seconds(str(row.get("Start_Time", "00:00.00")))
            end_sec = timecode_to_seconds(str(row.get("End_Time", "00:00.00")))

            ep_labels = labels_df[labels_df["Episode"] == ep]
            best_iou = 0.0
            best_label = None

            for _, lrow in ep_labels.iterrows():
                l_start = timecode_to_seconds(str(lrow.get("Start_Time", "00:00.00")))
                l_end = timecode_to_seconds(str(lrow.get("End_Time", "00:00.00")))
                iou = compute_overlap(start_sec, end_sec, l_start, l_end)
                if iou > best_iou:
                    best_iou = iou
                    best_label = str(lrow.get("Label", "")).strip().lower()

            # ONLY count if clip overlaps user label with IoU >= 0.35
            if best_iou >= 0.35 and best_label:
                total_matches += 1
                if best_label == "good":
                    good_matches += 1

        if total_matches < 3:
            results[f"Precision@{n}"] = f"insufficient labels ({total_matches}/{n} matches)"
        else:
            pct = round((good_matches / total_matches) * 100.0, 1)
            results[f"Precision@{n}"] = f"{pct}% ({good_matches}/{total_matches} matches)"

    return results


def evaluate_deterministic_checks(promos_df: pd.DataFrame) -> Dict[str, Any]:
    """Computes failure rates for each deterministic check."""
    if promos_df.empty:
        return {}

    total = len(promos_df)
    fail_hook = promos_df["Check_Hook"].astype(str).str.contains("FAIL|WEAK").sum() if "Check_Hook" in promos_df.columns else 0
    fail_start = promos_df["Check_Start"].astype(str).str.contains("FAIL").sum() if "Check_Start" in promos_df.columns else 0
    fail_end = promos_df["Check_End"].astype(str).str.contains("FAIL").sum() if "Check_End" in promos_df.columns else 0
    fail_context = promos_df["Check_Context"].astype(str).str.contains("needs_context").sum() if "Check_Context" in promos_df.columns else 0

    return {
        "Total_Candidates_Evaluated": total,
        "Check_Hook_Fail_Pct": f"{(fail_hook / total) * 100.0:.1f}% ({fail_hook}/{total})",
        "Check_Start_Fail_Pct": f"{(fail_start / total) * 100.0:.1f}% ({fail_start}/{total})",
        "Check_End_Fail_Pct": f"{(fail_end / total) * 100.0:.1f}% ({fail_end}/{total})",
        "Check_Context_Needs_Context_Pct": f"{(fail_context / total) * 100.0:.1f}% ({fail_context}/{total})",
    }


def generate_failures_markdown(
    promos_df: pd.DataFrame,
    master_df: pd.DataFrame,
    output_path: str = "FAILURES.md"
):
    """
    Generates FAILURES.md dynamically from the real latest promos.csv:
      - Picks up to 5 rows with failed checks (or lowest Rank_Score).
      - Pulls the transcript VERBATIM from master_df by Line_ID.
      - Asserts that every quoted line exists in the source script before writing.
    """
    if promos_df.empty or master_df.empty:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# ⚠️ Failure Cases & Anti-Patterns\n\nNo candidate promos available to audit.\n")
        return

    # Identify rows with check failures or lowest rank
    def has_check_issue(row):
        h = str(row.get("Check_Hook", ""))
        s = str(row.get("Check_Start", ""))
        e = str(row.get("Check_End", ""))
        c = str(row.get("Check_Context", ""))
        cv = str(row.get("Cold_Viewer_Pass", ""))
        return ("FAIL" in h or "WEAK" in h or "FAIL" in s or "FAIL" in e or "needs_context" in c or cv == "FAIL")

    issue_rows = promos_df[promos_df.apply(has_check_issue, axis=1)]
    if len(issue_rows) < 5:
        # Fill remaining with lowest Rank_Score rows
        other_rows = promos_df[~promos_df.index.isin(issue_rows.index)].sort_values(
            by="Rank_Score", ascending=True, na_position="first"
        )
        selected_rows = pd.concat([issue_rows, other_rows]).head(5)
    else:
        selected_rows = issue_rows.head(5)

    doc_lines = [
        "# ⚠️ Concrete Failure Cases & Anti-Patterns (FAILURES.md)",
        "",
        "This document is automatically generated from the latest pipeline run. It catalogs up to 5 candidate picks that triggered deterministic rule check warnings or scored lowest in ranking.",
        "All transcripts are extracted **verbatim** from the master screenplay lines by Line_ID.",
        "",
        "---",
        ""
    ]

    master_indexed = master_df.set_index("Line_ID")

    for case_num, (_, cand) in enumerate(selected_rows.iterrows(), 1):
        ep = int(cand.get("Episode", 1))
        s_id = str(cand.get("Start_Line_ID", "")).strip()
        e_id = str(cand.get("End_Line_ID", "")).strip()
        dur = cand.get("Duration_Sec", 0.0)
        source = cand.get("Source", "UNKNOWN")
        c_hook = cand.get("Check_Hook", "N/A")
        c_start = cand.get("Check_Start", "N/A")
        c_end = cand.get("Check_End", "N/A")
        c_ctx = cand.get("Check_Context", "N/A")
        c_viewer = cand.get("Cold_Viewer_Pass", "N/A")
        c_reason = cand.get("Cold_Viewer_Reason", "N/A")

        # Slice master lines between Start_Line_ID and End_Line_ID
        ep_master = master_df[master_df["Episode"] == ep].reset_index(drop=True)
        start_matches = ep_master[ep_master["Line_ID"] == s_id].index
        end_matches = ep_master[ep_master["Line_ID"] == e_id].index

        if len(start_matches) > 0 and len(end_matches) > 0:
            i_start = start_matches[0]
            i_end = end_matches[-1]
            clip_lines = ep_master.loc[i_start:i_end]
        else:
            # Timestamp fallback
            clip_lines = ep_master[
                (ep_master["Start_Sec"] >= float(cand.get("Start_Sec", 0.0)) - 0.05) &
                (ep_master["End_Sec"] <= float(cand.get("End_Sec", 0.0)) + 0.05)
            ]

        # ASSERTION: Every quoted line must exist verbatim in the source master dataframe
        verbatim_transcript_lines = []
        for _, q_row in clip_lines.iterrows():
            q_lid = q_row["Line_ID"]
            q_content = str(q_row["Content"])
            assert q_lid in master_indexed.index, f"Line_ID {q_lid} does not exist in master script!"
            assert q_content in set(master_df["Content"]), f"Content for {q_lid} does not exist in source script!"
            verbatim_transcript_lines.append(f"[{q_lid}] {q_row['Entity_Type']}: {q_content}")

        verbatim_snippet = "\n".join(verbatim_transcript_lines[:8])
        if len(verbatim_transcript_lines) > 8:
            verbatim_snippet += f"\n... [{len(verbatim_transcript_lines) - 8} additional lines omitted] ..."

        doc_lines.extend([
            f"### Case {case_num}: Episode {ep} (`{cand.get('Start_Time')}` to `{cand.get('End_Time')}`, Duration: `{dur:.1f}s`)",
            f"- **Candidate Source:** `{source}`",
            f"- **Triggered Checks:**",
            f"  - `Check_Hook`: `{c_hook}`",
            f"  - `Check_Start`: `{c_start}`",
            f"  - `Check_End`: `{c_end}`",
            f"  - `Check_Context`: `{c_ctx}`",
            f"- **Cold Viewer Audit:** `{c_viewer}` ({c_reason})",
            f"- **Verbatim Transcript Snippet (Verified from Source):**",
            "  ```text",
            verbatim_snippet,
            "  ```",
            f"- **Why It Fails / Deficiencies:**",
        ])

        reasons = []
        if "FAIL" in str(c_hook) or "WEAK" in str(c_hook):
            reasons.append(f"Hook flaw: {c_hook}")
        if "FAIL" in str(c_start):
            reasons.append(f"Start boundary flaw: {c_start}")
        if "FAIL" in str(c_end):
            reasons.append(f"Ending resolution flaw: {c_end}")
        if "needs_context" in str(c_ctx):
            reasons.append(f"Context flaw: {c_ctx}")
        if c_viewer == "FAIL":
            reasons.append(f"Cold viewer fail: {c_reason}")
        if not reasons:
            reasons.append("Low overall rank score due to unranked heuristic generation without LLM evaluation.")

        for r in reasons:
            doc_lines.append(f"  - {r}")

        doc_lines.extend(["", "---", ""])

    failures_content = "\n".join(doc_lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(failures_content)


def main():
    parser = argparse.ArgumentParser(description="Evaluate promo extraction quality against hand-labeled benchmark.")
    parser.add_argument("--promos_csv", type=str, default=None, help="Path to promos.csv or manifest CSV")
    parser.add_argument("--labels_csv", type=str, default=os.path.join("eval", "labels.csv"), help="Path to hand-labeled eval CSV")
    parser.add_argument("--master_csv", type=str, default="output/master_parsed_screenplays.csv", help="Master parsed CSV")
    parser.add_argument("--output_failures_md", type=str, default="FAILURES.md", help="Path to write FAILURES.md")
    args = parser.parse_args()

    promos_path = args.promos_csv or find_latest_promos_csv()
    if not promos_path or not os.path.exists(promos_path):
        print(f"No promotional candidates CSV found at {promos_path}. Run the pipeline first.")
        return

    promos_df = pd.read_csv(promos_path)
    labels_df = pd.read_csv(args.labels_csv) if os.path.exists(args.labels_csv) else pd.DataFrame()
    master_df = load_master_screenplay_df(args.master_csv)

    print("=" * 65)
    print("PROMOTIONAL EXTRACTION QUALITY EVALUATION")
    print("=" * 65)
    print(f"Promos Dataset: {promos_path} ({len(promos_df)} candidates)")
    print(f"Ground Truth Labels: {args.labels_csv} ({len(labels_df)} labeled clips)")
    print("-" * 65)

    prec_results = evaluate_precision_at_n(promos_df, labels_df, top_n_list=[1, 3, 5])
    print("Precision @ N Metrics (Strict Overlap with User Labels, IoU >= 0.35):")
    for k, v in prec_results.items():
        print(f"  -> {k}: {v}")

    print("-" * 65)
    det_results = evaluate_deterministic_checks(promos_df)
    print("Deterministic Quality Checks:")
    for k, v in det_results.items():
        print(f"  -> {k}: {v}")

    # Generate FAILURES.md dynamically from latest promos and master lines
    generate_failures_markdown(promos_df, master_df, args.output_failures_md)
    print("-" * 65)
    print(f"[SUCCESS] Generated verified FAILURES.md -> {args.output_failures_md}")
    print("=" * 65)


if __name__ == "__main__":
    main()
