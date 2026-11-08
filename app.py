"""
Kuku Microdrama Promotional Clip Extractor
==========================================
Interactive Streamlit Web Dashboard fulfilling Kuku FM microdrama promotional briefs:
  - Tab 1: 🚀 Run on a New Screenplay (upload .txt files or paste text, select provider/model, in-memory API key)
  - Tab 2: 📊 View Existing Results (inspect, filter, and export promotional campaigns)
"""

import os
import io
import json
import glob
import time
from typing import Optional, List, Dict, Any
import pandas as pd
import streamlit as st

from script_parser import parse_screenplay, episode_number
from promo_extractor import extract_promos_for_episode
from cross_episode_ranker import deduplicate_overlapping_candidates, run_llm_judge_ranking
from phase3_video_pipeline import generate_promo_srt, generate_ffmpeg_commands
from marketing_creative_generator import generate_marketing_creatives, calculate_optimal_thumbnail_timestamp
from llm_client import reset_run_stats, get_run_stats

# ==============================================================================
# PAGE CONFIGURATION & STYLING
# ==============================================================================
st.set_page_config(
    page_title="Kuku Microdrama Promo Extractor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        color: #E50914;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #4A4A4A;
        margin-bottom: 1.2rem;
    }
    .recommendation-box {
        background-color: #FFF5F5;
        border: 1px solid #FED7D7;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 25px;
    }
    .badge-pass {
        background-color: #C6F6D5;
        color: #22543D;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-fail {
        background-color: #FED7D7;
        color: #9B2C2C;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def find_latest_manifest() -> Optional[str]:
    """Finds the most recent promotional manifest CSV on disk."""
    run_manifests = sorted(glob.glob(os.path.join("output", "run_*", "promos.csv")), reverse=True)
    if run_manifests:
        return run_manifests[0]

    campaign_csvs = [
        os.path.join("output", "promo_campaign", "promo_campaign_manifest.csv"),
    ]
    for p in campaign_csvs:
        if os.path.exists(p):
            return p
    return None


def render_promo_table(df: pd.DataFrame):
    """Renders formatted table of promotional clips with clean headers and configs."""
    cols_to_show = [
        "Rank", "Episode", "Start_Time", "End_Time", "Duration_Sec",
        "Rank_Score", "Hook_Description", "Cliffhanger_Description",
        "Why_Post_First", "Check_Hook", "Check_Start", "Check_End", "Check_Context", "Cold_Viewer_Pass"
    ]
    existing_cols = [c for c in cols_to_show if c in df.columns]

    st.dataframe(
        df[existing_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn(format="#%d"),
            "Duration_Sec": st.column_config.NumberColumn(format="%.1f s"),
            "Rank_Score": st.column_config.NumberColumn(format="%.1f pts"),
        }
    )


# ==============================================================================
# HEADER
# ==============================================================================
st.markdown('<div class="main-header">🎬 Kuku Microdrama Promo Extractor</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    'Extract, validate, rank, and package high-converting promotional microdrama clips (20-60s) '
    'using Line-ID anchoring and deterministic quality checks.'
    '</div>',
    unsafe_allow_html=True
)

tab_run, tab_view = st.tabs(["🚀 Run on a New Screenplay", "📊 View Existing Results"])

# ==============================================================================
# TAB 1: RUN ON A NEW SCREENPLAY
# ==============================================================================
with tab_run:
    st.subheader("Ingest New Screenplay & Extract Promos")
    st.markdown("Upload one or more `.txt` screenplay files in Kuku format or paste the raw script below.")

    col_input1, col_input2 = st.columns([1, 1])

    with col_input1:
        uploaded_scripts = st.file_uploader(
            "Upload Screenplay .txt Files:",
            type=["txt"],
            accept_multiple_files=True,
            help="Upload raw screenplay text files conforming to Kuku format."
        )

    with col_input2:
        pasted_text = st.text_area(
            "Or Paste Screenplay Script Text:",
            height=140,
            placeholder="EPISODE NUMBER: Episode 1\nEPISODE LOGLINE: ...\nCONTINUITY NOTES: ...\n--- SCRIPT START ---\nSCENE 01..."
        )

    st.markdown("---")
    st.subheader("⚙️ Model & Provider Configuration")

    col_cfg1, col_cfg2, col_cfg3 = st.columns(3)

    with col_cfg1:
        provider_choice = st.selectbox(
            "LLM Provider:",
            options=["gemini", "openai-compatible"],
            index=0,
            help="Select Google Gemini or any OpenAI-compatible endpoint (Ollama, Groq, vLLM, OpenAI)."
        )

    with col_cfg2:
        if provider_choice == "gemini":
            model_name = st.selectbox(
                "Model:",
                options=["gemini-3.5-flash-lite", "gemini-3.5-flash"],
                index=0
            )
            base_url = None
        else:
            model_name = st.text_input("Model Name:", value="gpt-4o-mini")
            base_url = st.text_input("Base URL (optional):", value="https://api.openai.com/v1")

    with col_cfg3:
        # User API Key is stored in st.session_state ONLY; NEVER in os.environ
        if "user_api_key" not in st.session_state:
            st.session_state["user_api_key"] = ""

        api_key_input = st.text_input(
            "API Key (kept in session memory only):",
            type="password",
            value=st.session_state.get("user_api_key", ""),
            help="Your API key stays strictly in browser session memory and is never written to disk or environment."
        )
        if api_key_input:
            st.session_state["user_api_key"] = api_key_input

    btn_run = st.button("🚀 Extract & Rank Promos", type="primary", use_container_width=True)

    if btn_run:
        # Input validation
        has_files = uploaded_scripts is not None and len(uploaded_scripts) > 0
        has_text = pasted_text is not None and len(pasted_text.strip()) > 30

        if not has_files and not has_text:
            st.error("⚠️ Please upload at least one .txt screenplay file or paste script text above.")
        else:
            active_key = st.session_state.get("user_api_key", "").strip()
            # Fallback to env if session key empty
            if not active_key:
                active_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("LLM_API_KEY", "")

            if not active_key:
                st.error("⚠️ Please provide an API key for the selected provider to run the extraction.")
            else:
                try:
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    # Step 1: Parse input scripts
                    status_text.info("📖 Step 1/5: Parsing screenplay lines into structured master dataset...")
                    all_dfs = []

                    if has_files:
                        for uf in uploaded_scripts:
                            text_content = uf.read().decode("utf-8", errors="replace")
                            df_parsed = parse_screenplay(text_content, include_extended_metadata=True)
                            if not df_parsed.empty:
                                all_dfs.append(df_parsed)

                    if has_text:
                        df_pasted = parse_screenplay(pasted_text, include_extended_metadata=True)
                        if not df_pasted.empty:
                            all_dfs.append(df_pasted)

                    if not all_dfs:
                        st.error("Failed to parse any valid screenplay lines. Please check script formatting.")
                        st.stop()

                    master_df = pd.concat(all_dfs, ignore_index=True)
                    master_df["Episode"] = master_df["Episode"].apply(episode_number).astype(int)
                    progress_bar.progress(25)

                    # Step 2: Extract line-ID anchored candidates
                    episodes_found = sorted(list(master_df["Episode"].unique()))
                    status_text.info(f"🎯 Step 2/5: Extracting candidate promos across {len(episodes_found)} episodes (Line-ID anchored)...")

                    raw_candidates = []
                    for idx, ep_id in enumerate(episodes_found):
                        ep_df = master_df[master_df["Episode"] == ep_id].copy().reset_index(drop=True)
                        candidates = extract_promos_for_episode(
                            episode_df=ep_df,
                            master_df=master_df,
                            api_key=active_key,
                            provider=provider_choice,
                            model=model_name
                        )
                        raw_candidates.extend(candidates)

                    progress_bar.progress(60)

                    # Step 3: Deduplicate overlapping picks (>30%)
                    status_text.info(f"⚡ Step 3/5: Deduplicating overlapping clips across {len(raw_candidates)} candidates...")
                    deduped = deduplicate_overlapping_candidates(raw_candidates, overlap_threshold=0.30)
                    progress_bar.progress(75)

                    # Step 4: Run cross-episode ranking & judge evaluation
                    status_text.info("🏆 Step 4/5: Running Cross-Episode LLM Judge & Deterministic Rule Penalization...")
                    ranked_results = run_llm_judge_ranking(
                        candidates=deduped,
                        api_key=active_key,
                        provider=provider_choice,
                        model=model_name
                    )
                    progress_bar.progress(90)

                    # Step 5: Packaging & creatives
                    status_text.info("✨ Step 5/5: Generating on-screen hook overlays and social copy...")
                    for r in ranked_results:
                        creatives = generate_marketing_creatives(
                            episode_id=r.get("Episode", 1),
                            hook_desc=r.get("Hook_Description", ""),
                            cliffhanger_desc=r.get("Cliffhanger_Description", ""),
                            transcript_text=r.get("Transcript_Snippet", ""),
                            model_name=model_name,
                            api_key=active_key,
                            provider=provider_choice
                        )
                        h_opts = creatives.get("on_screen_hook_options", [])
                        r["On_Screen_Hook_1"] = h_opts[0] if len(h_opts) > 0 else "Must-Watch Betrayal"
                        r["Social_Caption"] = creatives.get("social_caption", "")

                    progress_bar.progress(100)
                    status_text.success("✅ Promotional Clip Extraction & Ranking Complete!")

                    results_df = pd.DataFrame(ranked_results).drop(columns=["raw_segments"], errors="ignore")
                    st.session_state["latest_results_df"] = results_df

                except Exception as e:
                    st.error(f"❌ An error occurred during pipeline execution: {str(e)}")

    # Display results if present in session state
    if "latest_results_df" in st.session_state and not st.session_state["latest_results_df"].empty:
        res_df = st.session_state["latest_results_df"]
        st.markdown("---")
        st.subheader("📋 Extraction Results & Campaign Manifest")

        # Top Recommendation Highlight Card
        top_clip = res_df.iloc[0]
        st.markdown('<div class="recommendation-box">', unsafe_allow_html=True)
        st.subheader(f"🏆 #1 Top Ranked Promo: Episode {top_clip['Episode']}")
        c_meta, c_info = st.columns([1, 2])
        with c_meta:
            st.markdown(f"**Exact Timeframe:** `{top_clip['Start_Time']}` $\\rightarrow$ `{top_clip['End_Time']}`")
            st.markdown(f"**Duration:** `{top_clip['Duration_Sec']:.1f}s`")
            st.markdown(f"**Rank Score:** :green[**{top_clip.get('Rank_Score', 0):.1f} / 100**]")
            if "On_Screen_Hook_1" in top_clip:
                st.markdown(f"**On-Screen Hook:**\n> *\"{top_clip['On_Screen_Hook_1']}\"*")
        with c_info:
            st.markdown(f"**🪝 Opening Hook:** {top_clip.get('Hook_Description')}")
            st.markdown(f"**⚡ Cliffhanger Ending:** {top_clip.get('Cliffhanger_Description')}")
            st.info(f"💡 **Why Post This First:** {top_clip.get('Why_Post_First', top_clip.get('Justification'))}")
        st.markdown('</div>', unsafe_allow_html=True)

        render_promo_table(res_df)

        # Export buttons
        st.markdown("#### 📥 Export Formatted Campaign Manifest")
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            csv_buf = io.StringIO()
            res_df.to_csv(csv_buf, index=False)
            st.download_button(
                "📥 Download Manifest (.CSV)",
                data=csv_buf.getvalue().encode("utf-8"),
                file_name="kuku_promos_manifest.csv",
                mime="text/csv",
                use_container_width=True
            )
        with d_col2:
            json_str = res_df.to_json(orient="records", indent=2)
            st.download_button(
                "📥 Download Manifest (.JSON)",
                data=json_str.encode("utf-8"),
                file_name="kuku_promos_manifest.json",
                mime="application/json",
                use_container_width=True
            )


# ==============================================================================
# TAB 2: VIEW EXISTING RESULTS
# ==============================================================================
with tab_view:
    st.subheader("Explore Existing Promotional Manifest")

    existing_file = st.sidebar.file_uploader(
        "Upload Extracted Manifest (CSV / JSON):",
        type=["csv", "json"],
        help="Upload an existing promos.csv or promos.json file"
    )

    loaded_df = None
    if existing_file is not None:
        try:
            if existing_file.name.endswith(".json"):
                loaded_df = pd.read_json(existing_file)
            else:
                loaded_df = pd.read_csv(existing_file)
        except Exception as e:
            st.error(f"Error reading uploaded file: {e}")

    if loaded_df is None or loaded_df.empty:
        latest_path = find_latest_manifest()
        if latest_path and os.path.exists(latest_path):
            try:
                loaded_df = pd.read_csv(latest_path)
            except Exception:
                loaded_df = None

    if loaded_df is None or loaded_df.empty:
        st.info(
            "👋 **No existing promotional manifest found.**\n\n"
            "Run the pipeline on a new screenplay in Tab 1, or execute `python run_pipeline.py` in your terminal."
        )
    else:
        # Filters in sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("🎯 Filter Promos")

        if "Episode" in loaded_df.columns:
            loaded_df["Episode"] = loaded_df["Episode"].apply(episode_number).astype(int)
            available_eps = sorted(list(loaded_df["Episode"].unique()))
            sel_eps = st.sidebar.multiselect("Filter by Episode:", options=available_eps, default=available_eps)
        else:
            sel_eps = []

        dur_slider = st.sidebar.slider(
            "Duration Filter (s):",
            min_value=20.0,
            max_value=60.0,
            value=(20.0, 60.0),
            step=0.5
        )

        min_score = 0.0
        if "Rank_Score" in loaded_df.columns:
            min_score = st.sidebar.slider(
                "Minimum Rank Score:",
                min_value=0.0,
                max_value=float(loaded_df["Rank_Score"].max() or 100.0),
                value=0.0,
                step=1.0
            )

        # Apply filtering
        filt_df = loaded_df.copy()
        if sel_eps and "Episode" in filt_df.columns:
            filt_df = filt_df[filt_df["Episode"].isin(sel_eps)]
        if "Duration_Sec" in filt_df.columns:
            filt_df = filt_df[(filt_df["Duration_Sec"] >= dur_slider[0]) & (filt_df["Duration_Sec"] <= dur_slider[1])]
        if "Rank_Score" in filt_df.columns:
            filt_df = filt_df[filt_df["Rank_Score"] >= min_score]

        # KPI Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Promos", f"{len(filt_df)}")
        avg_d = filt_df["Duration_Sec"].mean() if ("Duration_Sec" in filt_df.columns and not filt_df.empty) else 0.0
        m2.metric("Avg Duration", f"{avg_d:.1f}s")
        top_s = filt_df["Rank_Score"].max() if ("Rank_Score" in filt_df.columns and not filt_df.empty) else 0.0
        m3.metric("Top Rank Score", f"{top_s:.1f}")
        pass_rate = 0.0
        if "All_Checks_Passed" in filt_df.columns and not filt_df.empty:
            pass_rate = (filt_df["All_Checks_Passed"] == True).sum() / len(filt_df) * 100.0
        m4.metric("Rule Pass Rate", f"{pass_rate:.0f}%")

        if not filt_df.empty:
            top_rec = filt_df.iloc[0]
            st.markdown('<div class="recommendation-box">', unsafe_allow_html=True)
            st.subheader(f"🏆 Top Recommendation: Episode {top_rec.get('Episode', 1)}")
            st.markdown(f"**Why Post This First:** {top_rec.get('Why_Post_First', top_rec.get('Justification', 'N/A'))}")
            st.markdown('</div>', unsafe_allow_html=True)

            render_promo_table(filt_df)

            csv_dl = io.StringIO()
            filt_df.to_csv(csv_dl, index=False)
            st.download_button(
                "📥 Download Filtered Manifest (.CSV)",
                data=csv_dl.getvalue().encode("utf-8"),
                file_name="filtered_promos_manifest.csv",
                mime="text/csv"
            )
        else:
            st.warning("No clips match the selected filter criteria.")
