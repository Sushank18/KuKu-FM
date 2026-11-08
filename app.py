"""
Kuku Microdrama Promotional Clip Extractor
==========================================
Interactive Streamlit Web Dashboard for Stakeholder Presentation.
Ranks, filters, visualizes, and exports AI-extracted promotional microdrama clips (20-60s).

Deployment Target: Streamlit Community Cloud
"""

import os
import io
import glob
from typing import Optional, List, Dict, Any
import pandas as pd
import streamlit as st

from script_parser import episode_number

# ==============================================================================
# 1. PAGE CONFIGURATION & THEME STYLING
# ==============================================================================
st.set_page_config(
    page_title="Kuku Microdrama Promo Extractor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for polished stakeholder presentation
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        color: #E50914; /* Kuku cinematic red */
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #4A4A4A;
        margin-bottom: 1.5rem;
    }
    .recommendation-box {
        background-color: #FFF5F5;
        border: 1px solid #FED7D7;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 25px;
    }
    .badge-hook {
        background-color: #FEEBC8;
        color: #7B341E;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-cliff {
        background-color: #E2E8F0;
        color: #2D3748;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# 2. DATA LOADING (NO FABRICATED DATA)
# ==============================================================================
def find_latest_manifest() -> Optional[str]:
    """Finds the most recent promotional manifest CSV on disk."""
    # Check timestamped run directories first (output/run_*/promo_campaign_manifest.csv)
    run_manifests = sorted(glob.glob(os.path.join("output", "run_*", "promo_campaign_manifest.csv")), reverse=True)
    if run_manifests:
        return run_manifests[0]

    # Standard campaign manifest location
    standard_manifest = os.path.join("output", "promo_campaign", "promo_campaign_manifest.csv")
    if os.path.exists(standard_manifest):
        return standard_manifest
    return None


def load_dataset(uploaded_file) -> Optional[pd.DataFrame]:
    """
    Loads promotional data from an uploaded CSV or a local pipeline manifest.
    Returns None if no data is found (empty state).
    """
    if uploaded_file is not None:
        try:
            return pd.read_csv(uploaded_file)
        except Exception as e:
            st.sidebar.error(f"Error reading uploaded CSV: {e}")
            return None

    manifest_path = find_latest_manifest()
    if manifest_path and os.path.exists(manifest_path):
        try:
            df = pd.read_csv(manifest_path)
            if not df.empty:
                return df
        except Exception:
            return None

    return None


# ==============================================================================
# 3. DATA NORMALIZATION & ORDERING
# ==============================================================================
def normalize_and_order_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalizes column aliases, ensures numeric episode representation,
    and applies sorting (by Rank/Rank_Score if present, else preserves file order).
    """
    data = df.copy()

    col_mapping = {
        "Start_Timecode": "Start_Time",
        "Raw_Start_Time": "Start_Time",
        "End_Timecode": "End_Time",
        "Raw_End_Time": "End_Time",
        "Hook": "Hook_Description",
        "Cliffhanger": "Cliffhanger_Description"
    }
    for old_col, new_col in col_mapping.items():
        if old_col in data.columns and new_col not in data.columns:
            data[new_col] = data[old_col]

    # Normalize Episode as integer
    if "Episode" in data.columns:
        data["Episode"] = data["Episode"].apply(episode_number).astype(int)
    else:
        data["Episode"] = 1

    # Ensure Duration_Sec is numeric
    if "Duration_Sec" in data.columns:
        data["Duration_Sec"] = pd.to_numeric(data["Duration_Sec"], errors="coerce").fillna(30.0)
    elif "Snapped_Duration_Sec" in data.columns:
        data["Duration_Sec"] = pd.to_numeric(data["Snapped_Duration_Sec"], errors="coerce").fillna(30.0)
    else:
        data["Duration_Sec"] = 30.0

    # Ensure required textual columns exist
    for col in ["Start_Time", "End_Time", "Hook_Description", "Cliffhanger_Description", "Justification"]:
        if col not in data.columns:
            data[col] = "N/A"

    # Sorting order logic:
    # If Rank_Score or Rank is present, sort by it; otherwise maintain natural file order.
    if "Rank_Score" in data.columns:
        data["Rank_Score"] = pd.to_numeric(data["Rank_Score"], errors="coerce").fillna(0.0)
        data = data.sort_values(by="Rank_Score", ascending=False).reset_index(drop=True)
    elif "Rank" in data.columns:
        data["Rank"] = pd.to_numeric(data["Rank"], errors="coerce").fillna(999)
        data = data.sort_values(by="Rank", ascending=True).reset_index(drop=True)
    else:
        data = data.reset_index(drop=True)

    return data


# ==============================================================================
# 4. APPLICATION HEADER & CONTEXT
# ==============================================================================
st.markdown('<div class="main-header">🎬 Kuku Microdrama Promo Extractor</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    'AI-powered promotional clip extraction pipeline for vertical microdrama screenplays. '
    'Deterministically identifies <b>20 to 60-second standalone promotional hooks</b> '
    'optimized for TikTok, Meta Reels, and YouTube Shorts.'
    '</div>',
    unsafe_allow_html=True
)

with st.expander("ℹ️ How the Extraction Pipeline Operates", expanded=False):
    st.markdown("""
    1. **Deterministic Script Parsing:** Raw screenplay text files are parsed into a structured Pandas DataFrame with millisecond timestamps and character emotion tags.
    2. **AI-Driven Promo Reasoning:** An LLM evaluates dramatic tension across each episode to isolate the single highest-converting promotional clip.
    3. **Microdrama Structural Constraints:**
       - **Strict Duration:** Clips are strictly constrained between **20.0 and 60.0 seconds**.
       - **Opening Hook:** Must open on dialogue with high tension, a reveal, confrontation, or slap (no continuation fragments like `...`).
       - **Ending Cliffhanger:** Cuts off at peak tension, maximizing viewer conversion.
       - **Standalone Continuity:** Requires zero prior context to understand the stakes.
    4. **Subtitles & Video Export:** Automatically generates synchronized `.srt` subtitle files and frame-accurate FFmpeg slicing scripts.
    """)


# ==============================================================================
# 5. SIDEBAR: DATA LOADING, API KEY & FILTER CONTROLS
# ==============================================================================
st.sidebar.header("🔑 API Configuration")

default_secret_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        default_secret_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

if not default_secret_key:
    default_secret_key = os.getenv("GEMINI_API_KEY", "")

gemini_key_input = st.sidebar.text_input(
    "Google Gemini API Key:",
    value=default_secret_key if default_secret_key else "",
    type="password",
    help="Add your API key here or configure it in Streamlit Cloud Settings > Secrets."
)

if gemini_key_input:
    os.environ["GEMINI_API_KEY"] = gemini_key_input
    st.sidebar.success("✅ Gemini API Key Active")

st.sidebar.markdown("---")
st.sidebar.header("📁 Data Source & Filters")

uploaded_file = st.sidebar.file_uploader(
    "Upload Extracted Promos Manifest (CSV)",
    type=["csv"],
    help="Upload promo_campaign_manifest.csv or any promotional clips CSV."
)

raw_df = load_dataset(uploaded_file)

# If no dataset exists, display empty state and stop execution
if raw_df is None or raw_df.empty:
    st.info(
        "👋 **No promotional clips manifest found.**\n\n"
        "To get started:\n"
        "1. Run the pipeline in your terminal: `python run_pipeline.py`\n"
        "2. Or upload a manifest CSV using the sidebar on the left."
    )
    st.stop()

# Normalize and format dataset
df_normalized = normalize_and_order_data(raw_df)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Refine Clips")

# Filter 1: Episode Selector (guaranteed integer sorting, never raises TypeError)
available_episodes = sorted(list(df_normalized["Episode"].unique()))
selected_episodes = st.sidebar.multiselect(
    "Filter by Episode Number:",
    options=available_episodes,
    default=available_episodes
)

# Filter 2: Duration Slider (Strict 20-60s)
min_dur_slider, max_dur_slider = st.sidebar.slider(
    "Clip Duration Range (Seconds):",
    min_value=20.0,
    max_value=60.0,
    value=(20.0, 60.0),
    step=0.5,
    help="Filter clips strictly within microdrama duration constraints."
)

# Filter 3: Minimum Score Slider (defaults to 0 so no rows are hidden by default)
if "Rank_Score" in df_normalized.columns:
    max_rank_val = float(df_normalized["Rank_Score"].max() or 100.0)
    min_score = st.sidebar.slider(
        "Minimum Rank Score:",
        min_value=0.0,
        max_value=max_rank_val,
        value=0.0,
        step=1.0,
        help="Defaults to 0 so all rows remain visible."
    )
    score_mask = df_normalized["Rank_Score"] >= min_score
else:
    score_mask = True

# Apply filters
filtered_df = df_normalized[
    (df_normalized["Episode"].isin(selected_episodes)) &
    (df_normalized["Duration_Sec"] >= min_dur_slider) &
    (df_normalized["Duration_Sec"] <= max_dur_slider) &
    score_mask
].copy()


# ==============================================================================
# 6. EXECUTIVE KPI METRICS
# ==============================================================================
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    st.metric("Total Extracted Clips", f"{len(filtered_df)}")

with kpi2:
    avg_dur = filtered_df["Duration_Sec"].mean() if not filtered_df.empty else 0.0
    st.metric("Avg Clip Duration", f"{avg_dur:.1f} sec")

with kpi3:
    top_ep = filtered_df.iloc[0]["Episode"] if not filtered_df.empty else "N/A"
    st.metric("Top Recommended Episode", f"Episode {top_ep}")

with kpi4:
    if "Rank_Score" in filtered_df.columns:
        top_score_val = f"{filtered_df['Rank_Score'].max():.1f}"
        st.metric("Top Rank Score", top_score_val)
    else:
        st.metric("Pipeline Status", "Completed")

st.markdown("<br>", unsafe_allow_html=True)


# ==============================================================================
# 7. DEDICATED SECTION: TOP RECOMMENDATION (#1 RANKED PROMO)
# ==============================================================================
if not filtered_df.empty:
    top_clip = filtered_df.iloc[0]

    st.markdown('<div class="recommendation-box">', unsafe_allow_html=True)
    st.subheader(f"🏆 Top Recommendation: Episode {top_clip['Episode']} Promotional Clip")
    
    col_rec_meta, col_rec_just = st.columns([1, 2])

    with col_rec_meta:
        st.markdown(f"**Exact Timeframe:** `{top_clip['Start_Time']}` to `{top_clip['End_Time']}`")
        st.markdown(f"**Duration:** `{top_clip['Duration_Sec']:.1f} seconds`")
        if "Rank_Score" in top_clip and pd.notna(top_clip["Rank_Score"]):
            st.markdown(f"**Rank Score:** :green[**{top_clip['Rank_Score']}**]")
        if "On_Screen_Hook_1" in top_clip and pd.notna(top_clip["On_Screen_Hook_1"]):
            st.markdown(f"**Suggested On-Screen Hook:**\n> *\"{top_clip['On_Screen_Hook_1']}\"*")

    with col_rec_just:
        st.markdown(f"**🪝 Opening Hook (First 3 Seconds):**\n<span class='badge-hook'>HOOK</span> {top_clip['Hook_Description']}", unsafe_allow_html=True)
        st.markdown(f"**⚡ Cliffhanger Ending:**\n<span class='badge-cliff'>CLIFFHANGER</span> {top_clip['Cliffhanger_Description']}", unsafe_allow_html=True)
        st.info(f"💡 **Why Post This First:** {top_clip['Justification']}")

    st.markdown('</div>', unsafe_allow_html=True)
else:
    st.warning("⚠️ No promotional clips match your current filter settings. Adjust the sidebar filters to view clips.")


# ==============================================================================
# 8. DATA VISUALIZATION TABLE & DETAILED EXPANDERS
# ==============================================================================
st.subheader("📋 Promotional Clips Catalog")

base_columns = [
    "Episode",
    "Start_Time",
    "End_Time",
    "Duration_Sec",
    "Hook_Description",
    "Cliffhanger_Description",
    "Justification"
]
if "Rank_Score" in filtered_df.columns:
    display_columns = ["Episode", "Start_Time", "End_Time", "Duration_Sec", "Rank_Score", "Hook_Description", "Cliffhanger_Description", "Justification"]
else:
    display_columns = base_columns

column_headers = {
    "Episode": "Episode",
    "Start_Time": "Start Time",
    "End_Time": "End Time",
    "Duration_Sec": "Duration (s)",
    "Rank_Score": "Rank Score",
    "Hook_Description": "Hook Event",
    "Cliffhanger_Description": "Cliffhanger Event",
    "Justification": "Standalone Justification"
}

st.dataframe(
    filtered_df[display_columns].rename(columns=column_headers),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Duration (s)": st.column_config.NumberColumn(format="%.1f s"),
    }
)

# Expandable cards for creative details
st.markdown("#### 🔍 Clip Detail Inspector & Social Copy")
for idx, row in filtered_df.iterrows():
    with st.expander(f"Episode {row['Episode']} — {row['Duration_Sec']:.1f}s Clip"):
        d1, d2 = st.columns(2)
        with d1:
            st.markdown(f"**Timecodes:** `{row['Start_Time']}` $\\rightarrow$ `{row['End_Time']}`")
            st.markdown(f"**Hook:** {row['Hook_Description']}")
            st.markdown(f"**Cliffhanger:** {row['Cliffhanger_Description']}")
        with d2:
            st.markdown(f"**Standalone Justification:**\n{row['Justification']}")
            if "Social_Caption" in row and pd.notna(row["Social_Caption"]):
                st.text_area("Suggested Social Caption:", value=str(row["Social_Caption"]), height=80, key=f"caption_{idx}")


# ==============================================================================
# 9. EXPORT & DOWNLOAD FUNCTIONALITY
# ==============================================================================
st.markdown("---")
c_down1, c_down2 = st.columns([3, 1])

with c_down1:
    st.markdown("**Ready to deliver to video editors and media buyers?** Download the filtered manifest.")

with c_down2:
    csv_buffer = io.StringIO()
    filtered_df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    st.download_button(
        label="📥 Download Manifest (.CSV)",
        data=csv_bytes,
        file_name="kuku_promotional_clips_manifest.csv",
        mime="text/csv",
        use_container_width=True
    )
