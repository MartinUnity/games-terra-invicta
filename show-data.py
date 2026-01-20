from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

# -----------------------------------------------------------------------------
# 1. CONFIG & SETUP
# -----------------------------------------------------------------------------
RELOAD_TIMESEC = 120
st.set_page_config(page_title="Terra Invicta Tracker", layout="wide")

# Define the columns exactly as your watcher script outputs them
COL_NAMES = [
    "date",
    "nation_name",
    "gdp_capita",
    "population_millions",
    "inequality",
    "democracy",
    "unrest",
    "cohesion",
    "monthly_research",
    "monthly_ip",
    "cp_maintenance_cost",
    "ui_cost_per_point",
    "efficiency_research",
    "efficiency_ip",
    "mc_built",
    "mc_cap",
    "mc_utilization",
]


# -----------------------------------------------------------------------------
# 2. DATA LOADING
# -----------------------------------------------------------------------------
@st.cache_data(ttl=5)
def load_data():
    try:
        # Load CSV (header=0 to skip the file header if it exists)
        df = pd.read_csv("campaign_history.csv", header=0, names=COL_NAMES, encoding="utf-8-sig")

        # Filter out repeated headers if file was appended incorrectly
        df = df[df["nation_name"] != "nation_name"]

        # Convert numeric columns
        numeric_cols = [
            "gdp_capita",
            "population_millions",
            "inequality",
            "democracy",
            "unrest",
            "cohesion",
            "monthly_research",
            "monthly_ip",
            "cp_maintenance_cost",
            "ui_cost_per_point",
            "efficiency_research",
            "efficiency_ip",
            "mc_built",
            "mc_cap",
            "mc_utilization",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Parse Dates
        if "date" in df.columns:
            df["date_obj"] = pd.to_datetime(df["date"])

        return df
    except Exception as e:
        return pd.DataFrame(columns=COL_NAMES)


# Load data immediately
df = load_data()

# -----------------------------------------------------------------------------
# 3. SIDEBAR (CONTROLS & CLOCK & DATE FILTER)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Dashboard Settings")

    # --- A. Auto-Refresh Logic ---
    use_autorefresh = st.checkbox(f"📡 Live Auto-Refresh ({RELOAD_TIMESEC}s)", value=False, key="sidebar_autorefresh")

    if use_autorefresh:
        st_autorefresh(interval=RELOAD_TIMESEC * 1000, key="dataframerefresh")

        last_update = datetime.now().strftime("%H:%M:%S")
        st.caption(f"✅ Data fetched at: **{last_update}**")

        # Javascript Clock Injection
        clock_html = """
        <div style="font-family: sans-serif; font-size: 14px; color: #888;
            margin-top: 5px; padding: 5px; border: 1px solid #444;
            border-radius: 5px; text-align: center; background-color: #262730;">
            <span style="font-weight:bold;">Current Time:</span>
            <span id="live_clock"></span>
        </div>
        <script>
        function updateClock() {
            var now = new Date();
            var timeString = now.toLocaleTimeString([], {hour12: false});
            document.getElementById('live_clock').innerHTML = timeString;
        }
        setInterval(updateClock, 1000);
        updateClock();
        </script>
        """
        components.html(clock_html, height=50)

        if st.button("🔄 Force Refresh Now"):
            st.rerun()

    st.divider()

    # --- B. Date Range Filter (The New Feature) ---
    st.markdown("### 📅 Time Machine")

    # Ensure we have the tool for month math
    from dateutil.relativedelta import relativedelta

    if not df.empty and "date_obj" in df.columns:
        min_date = df["date_obj"].min().to_pydatetime()
        max_date = df["date_obj"].max().to_pydatetime()

        # 1. Quick Select Presets
        preset = st.radio(
            "Quick Select:",
            ["All Time", "Last 1 Month", "Last 3 Months", "Last 6 Months", "Last 1 Year"],
            horizontal=True,
            key="date_preset",
        )

        # Calculate slider defaults based on preset
        if preset == "All Time":
            start_val, end_val = min_date, max_date
        else:
            # Check if the latest date is the 1st of the month (User Logic: Snap to clean months)
            is_first_of_month = max_date.day == 1

            # Map presets to clean months
            months_map = {"Last 1 Month": 1, "Last 3 Months": 3, "Last 6 Months": 6, "Last 1 Year": 12}

            if is_first_of_month and preset in months_map:
                # Snap exactly X months back (e.g. June 1st -> May 1st)
                start_val = max(min_date, max_date - relativedelta(months=months_map[preset]))
            else:
                # Fallback: Standard sliding window (30/90 days) if not on the 1st
                days_map = {"Last 1 Month": 30, "Last 3 Months": 90, "Last 6 Months": 180, "Last 1 Year": 365}
                days_back = days_map.get(preset, 0)
                start_val = max(min_date, max_date - pd.Timedelta(days=days_back))

            end_val = max_date

        # 2. The Slider (Allows fine-tuning)
        selected_range = st.slider(
            "Select Date Range:", min_value=min_date, max_value=max_date, value=(start_val, end_val), format="MM/DD/YY"
        )

        # 3. Apply Filter Globally
        start_date_sel, end_date_sel = selected_range
        mask = (df["date_obj"] >= start_date_sel) & (df["date_obj"] <= end_date_sel)
        df_filtered = df.loc[mask]

        # Show span info
        duration = end_date_sel - start_date_sel
        days = duration.days
        st.info(f"Viewing **{days} days** of history.")

    else:
        st.warning("Waiting for data...")
        df_filtered = df  # Fallback

# -----------------------------------------------------------------------------
# 4. MAIN TABS
# -----------------------------------------------------------------------------
tab1, tab2 = st.tabs(["📊 Global Meta Analysis", "🌍 Nation Detailed View"])

# UPDATE: Use df_filtered here instead of df!
if not df_filtered.empty:
    latest_snapshot = df_filtered.sort_values("date").groupby("nation_name").tail(1)

    # Also update the 'df' reference inside Tab 1 to use 'df_filtered'
    # For simplicity, you can just re-assign df = df_filtered for the rest of the script
    # This is safe because we are at the top level of the script run
    df = df_filtered
else:
    latest_snapshot = pd.DataFrame()

# =============================================================================
# TAB 1: GLOBAL META (GRAPHS)
# =============================================================================
with tab1:
    if df.empty:
        st.error("No data available.")
    else:
        # -------------------------------------------------------------------------
        # PART A: ECONOMIC VELOCITY (GDP Trends)
        # -------------------------------------------------------------------------
        st.markdown("### 📈 Economic Velocity")
        st.info("Gray = Base. **Green = Growth**. **Red = Loss**. Text shows: **Gain (Growth %)**")

        # 1. CONTROLS
        col_view, col_sort = st.columns(2)
        with col_view:
            view_mode = st.radio(
                "View Metric:",
                ["Per Capita ($)", "Total National GDP ($B)", "True Efficiency ($B / Cap Cost)"],
                horizontal=True,
                key="gdp_view_mode",
            )
        with col_sort:
            sort_mode = st.radio(
                "Sort By:",
                ["Highest Value", "Largest Gain ($)", "Fastest Growth (%)"],
                horizontal=True,
                index=1,
                key="gdp_sort_mode",
            )

        # Toggle: Focus Only on Change
        show_delta_only = st.checkbox("🔍 Focus only on Change (Hide Base Values)", value=False, key="gdp_delta_only")

        # 2. PREPARE DATA
        gdp_trends = (
            df.sort_values("date")
            .groupby("nation_name")
            .agg(
                old_gdp_cap=("gdp_capita", "first"),
                new_gdp_cap=("gdp_capita", "last"),
                old_pop=("population_millions", "first"),
                new_pop=("population_millions", "last"),
                old_cp_cost=("cp_maintenance_cost", "first"),
                new_cp_cost=("cp_maintenance_cost", "last"),
                inequality=("inequality", "last"),
            )
            .reset_index()
        )

        # 3. HELPER: Calculate Total GDP ($B)
        gdp_trends["old_total_gdp"] = (gdp_trends["old_gdp_cap"] * gdp_trends["old_pop"]) / 1000
        gdp_trends["new_total_gdp"] = (gdp_trends["new_gdp_cap"] * gdp_trends["new_pop"]) / 1000

        # 4. CALCULATE CHOSEN METRIC
        if view_mode == "Per Capita ($)":
            gdp_trends["old_val"] = gdp_trends["old_gdp_cap"]
            gdp_trends["new_val"] = gdp_trends["new_gdp_cap"]
            axis_title = "GDP Per Capita ($)"
            gdp_trends["meta_info"] = "Pop: " + gdp_trends["new_pop"].round(1).astype(str) + "M"

            def format_delta(x):
                return f"${x:,.0f}"

        elif view_mode == "Total National GDP ($B)":
            gdp_trends["old_val"] = gdp_trends["old_total_gdp"]
            gdp_trends["new_val"] = gdp_trends["new_total_gdp"]
            axis_title = "National GDP (Billions)"
            gdp_trends["meta_info"] = "Pop: " + gdp_trends["new_pop"].round(1).astype(str) + "M"

            def format_delta(x):
                return f"${x/1000:.2f}T" if abs(x) >= 1000 else f"${x:,.1f}B"

        else:  # True Efficiency
            gdp_trends["old_val"] = gdp_trends["old_total_gdp"] / gdp_trends["old_cp_cost"].replace(0, 0.1)
            gdp_trends["new_val"] = gdp_trends["new_total_gdp"] / gdp_trends["new_cp_cost"].replace(0, 0.1)
            axis_title = "GDP Yield per 1.0 Cap Cost ($B)"
            gdp_trends["meta_info"] = "Cost: " + gdp_trends["new_cp_cost"].round(1).astype(str) + " CP"

            def format_delta(x):
                return f"${x:,.1f}B"

        # 5. COMMON CALCULATIONS
        gdp_trends["delta"] = gdp_trends["new_val"] - gdp_trends["old_val"]
        gdp_trends["pct_change"] = gdp_trends.apply(
            lambda r: ((r["new_val"] - r["old_val"]) / r["old_val"] * 100) if r["old_val"] > 0 else 0, axis=1
        )
        gdp_trends["base_val"] = gdp_trends[["old_val", "new_val"]].min(axis=1)
        gdp_trends["status"] = gdp_trends["delta"].apply(lambda x: "Growth" if x >= 0 else "Recession")

        gdp_trends["label"] = gdp_trends.apply(
            lambda x: f"{'+' if x['delta']>=0 else ''}{format_delta(x['delta'])} ({x['pct_change']:+.1f}%)", axis=1
        )

        # 6. SORTING & SUBSET
        if sort_mode == "Fastest Growth (%)":
            gdp_trends = gdp_trends.sort_values("pct_change", ascending=False)
        elif sort_mode == "Largest Gain ($)":
            gdp_trends = gdp_trends.sort_values("delta", ascending=False)
        else:
            gdp_trends = gdp_trends.sort_values("new_val", ascending=False)

        gdp_subset = gdp_trends.head(40).copy()
        gdp_height = 100 + (len(gdp_subset) * 30)

        # Calculate text anchor in Python to avoid Altair errors
        gdp_subset["text_anchor"] = gdp_subset[["old_val", "new_val"]].max(axis=1)

        # 7. BUILD CHART (CONDITIONAL)
        base_gdp = alt.Chart(gdp_subset).encode(y=alt.Y("nation_name", sort=None, title=None))

        if show_delta_only:
            # MODE A: DELTA ONLY (Diverging Bar Chart)
            chart = base_gdp.mark_bar().encode(
                x=alt.X("delta", title=f"Change in {axis_title}"),
                color=alt.Color(
                    "status", scale=alt.Scale(domain=["Growth", "Recession"], range=["#2ecc71", "#e74c3c"]), legend=None
                ),
                tooltip=["nation_name", "label", "meta_info", "inequality", "delta"],
            )

            # FIX: Split text into two layers instead of using conditional encoding
            # 1. Positive Delta -> Align Left (dx=5)
            text_pos = (
                base_gdp.transform_filter(alt.datum.delta >= 0)
                .mark_text(align="left", dx=5, clip=False)
                .encode(x="delta", text="label", color=alt.value("white"))
            )

            # 2. Negative Delta -> Align Right (dx=-5)
            text_neg = (
                base_gdp.transform_filter(alt.datum.delta < 0)
                .mark_text(align="right", dx=-5, clip=False)
                .encode(x="delta", text="label", color=alt.value("white"))
            )

            final_chart = chart + text_pos + text_neg

        else:
            # MODE B: STANDARD (Base + Delta Stack)
            bar_base = base_gdp.mark_bar(color="#333333").encode(x=alt.X("base_val", title=axis_title))

            bar_delta = base_gdp.mark_bar().encode(
                x="old_val",
                x2="new_val",
                color=alt.Color(
                    "status", scale=alt.Scale(domain=["Growth", "Recession"], range=["#2ecc71", "#e74c3c"]), legend=None
                ),
                tooltip=["nation_name", "label", "meta_info", "inequality", "delta"],
            )

            text = base_gdp.mark_text(align="left", dx=5, clip=False).encode(
                x=alt.X("text_anchor"), text="label", color=alt.value("white")
            )

            final_chart = bar_base + bar_delta + text

        st.altair_chart(final_chart.properties(height=gdp_height), use_container_width=True)
        st.divider()

        # -------------------------------------------------------------
        # PART B: MISSION CONTROL
        # -------------------------------------------------------------
        st.markdown("### 🛰️ Mission Control Logistics")
        st.info("Gray Bar = Max Capacity. Colored Bar = Currently Built.")

        c1, c2 = st.columns(2)
        with c1:
            show_tiny = st.checkbox("Show tiny nations (Cap <= 2)", value=False, key="mc_show_tiny")
        with c2:
            hide_capped = st.checkbox("Hide fully capped nations (Red)", value=False, key="mc_hide_capped")

        mc_subset = latest_snapshot.copy()
        if not show_tiny:
            mc_subset = mc_subset[(mc_subset["mc_cap"] > 2) | (mc_subset["mc_built"] > 0)]
        if hide_capped:
            mc_subset = mc_subset[mc_subset["mc_built"] < mc_subset["mc_cap"]]

        if not mc_subset.empty:

            def get_mc_status(row):
                if row["mc_built"] >= row["mc_cap"]:
                    return "Capped (Stop)"
                elif row["mc_utilization"] > 80:
                    return "Warning (>80%)"
                else:
                    return "Building (<80%)"

            mc_subset["status"] = mc_subset.apply(get_mc_status, axis=1)
            mc_subset["label"] = mc_subset.apply(lambda x: f"{int(x['mc_built'])} / {int(x['mc_cap'])}", axis=1)

            base_mc = alt.Chart(mc_subset).encode(y=alt.Y("nation_name", sort="-x", title=None))
            bg_mc = base_mc.mark_bar(color="#333333").encode(x=alt.X("mc_cap", title="Mission Control Slots"))
            fg_mc = base_mc.mark_bar().encode(
                x="mc_built",
                color=alt.Color(
                    "status",
                    scale=alt.Scale(
                        domain=["Building (<80%)", "Warning (>80%)", "Capped (Stop)"],
                        range=["#2ecc71", "#f1c40f", "#e74c3c"],
                    ),
                    legend=None,
                ),
                tooltip=["nation_name", "mc_built", "mc_cap", "mc_utilization"],
            )
            txt_mc = base_mc.mark_text(align="left", dx=5, clip=False).encode(
                x="mc_cap", text="label", color=alt.value("white")
            )

            st.altair_chart(
                (bg_mc + fg_mc + txt_mc).properties(height=100 + len(mc_subset) * 40), use_container_width=True
            )
        else:
            st.success("All MC optimized! No nations to display.")

        st.divider()

        # -------------------------------------------------------------
        # PART C: SCATTER PLOTS
        # -------------------------------------------------------------
        st.subheader("📊 Strategic Efficiency")
        color_metric = st.radio(
            "Color Bubbles By:", ["Democracy", "Unrest", "Inequality"], index=1, horizontal=True, key="scatter_color"
        )

        scale_opts = (
            alt.Scale(scheme="turbo")
            if color_metric == "Democracy"
            else alt.Scale(scheme="reds") if color_metric == "Unrest" else alt.Scale(scheme="magma")
        )

        c_res = (
            alt.Chart(latest_snapshot)
            .mark_circle(size=120)
            .encode(
                x=alt.X("cp_maintenance_cost", title="Nation Size (CP Cost)"),
                y=alt.Y("efficiency_research", title="Science Yield per CP"),
                color=alt.Color(color_metric.lower(), scale=scale_opts),
                tooltip=["nation_name", "monthly_research", "efficiency_research", color_metric.lower()],
            )
            .interactive()
        )
        st.altair_chart(c_res, use_container_width=True)

# =============================================================================
# TAB 2: DETAILED VIEW (Raw Data)
# =============================================================================
with tab2:
    st.markdown("### 🌍 Nation Details")
    if not df.empty:
        all_nations = sorted(df["nation_name"].unique())
        selected_nation = st.selectbox("Select a Nation to inspect:", all_nations, index=0, key="tab2_nation_select")

        nation_data = df[df["nation_name"] == selected_nation].sort_values("date", ascending=False)

        st.dataframe(
            nation_data.style.format(
                {
                    "gdp_capita": "${:,.0f}",
                    "population_millions": "{:.1f} M",
                    "monthly_research": "{:.1f}",
                    "monthly_ip": "{:.1f}",
                    "efficiency_research": "{:.2f}",
                    "efficiency_ip": "{:.2f}",
                }
            ),
            use_container_width=True,
        )
    else:
        st.warning("No data found.")
