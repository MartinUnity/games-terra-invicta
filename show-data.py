from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dateutil.relativedelta import relativedelta
from streamlit_autorefresh import st_autorefresh

# -----------------------------------------------------------------------------
# 1. CONFIG & SETUP
# -----------------------------------------------------------------------------
RELOAD_TIMESEC = 120
st.set_page_config(page_title="Terra Invicta Tracker", layout="wide")

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
        df = pd.read_csv("campaign_history.csv", header=0, names=COL_NAMES, encoding="utf-8-sig")
        df = df[df["nation_name"] != "nation_name"]  # Filter repeat headers

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

        if "date" in df.columns:
            df["date_obj"] = pd.to_datetime(df["date"])

        return df
    except Exception:
        return pd.DataFrame(columns=COL_NAMES)


df = load_data()

# -----------------------------------------------------------------------------
# 3. SIDEBAR
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Dashboard Settings")

    # Auto-Refresh
    use_autorefresh = st.checkbox(f"📡 Live Auto-Refresh ({RELOAD_TIMESEC}s)", value=False, key="sidebar_autorefresh")
    if use_autorefresh:
        st_autorefresh(interval=RELOAD_TIMESEC * 1000, key="dataframerefresh")
        st.caption(f"✅ Data fetched at: **{datetime.now().strftime('%H:%M:%S')}**")

        # Clock
        clock_html = """
        <div style="font-family: sans-serif; font-size: 14px; color: #888;
            margin-top: 5px; padding: 5px; border: 1px solid #444;
            border-radius: 5px; text-align: center; background-color: #262730;">
            <span style="font-weight:bold;">Current Time:</span> <span id="live_clock"></span>
        </div>
        <script>
        function updateClock() {
            var now = new Date();
            document.getElementById('live_clock').innerHTML = now.toLocaleTimeString([], {hour12: false});
        }
        setInterval(updateClock, 1000);
        updateClock();
        </script>
        """
        components.html(clock_html, height=50)
        if st.button("🔄 Force Refresh Now"):
            st.rerun()

    st.divider()

    # Time Machine Filter
    st.markdown("### 📅 Time Machine")
    if not df.empty and "date_obj" in df.columns:
        min_date = df["date_obj"].min().to_pydatetime()
        max_date = df["date_obj"].max().to_pydatetime()

        preset = st.radio(
            "Quick Select:",
            ["All Time", "Last 1 Month", "Last 3 Months", "Last 6 Months", "Last 1 Year"],
            horizontal=True,
            key="date_preset",
        )

        if preset == "All Time":
            start_val, end_val = min_date, max_date
        else:
            is_first_of_month = max_date.day == 1
            months_map = {"Last 1 Month": 1, "Last 3 Months": 3, "Last 6 Months": 6, "Last 1 Year": 12}

            if is_first_of_month and preset in months_map:
                start_val = max(min_date, max_date - relativedelta(months=months_map[preset]))
            else:
                days_map = {"Last 1 Month": 30, "Last 3 Months": 90, "Last 6 Months": 180, "Last 1 Year": 365}
                start_val = max(min_date, max_date - pd.Timedelta(days=days_map.get(preset, 0)))
            end_val = max_date

        selected_range = st.slider(
            "Select Date Range:", min_value=min_date, max_value=max_date, value=(start_val, end_val), format="MM/DD/YY"
        )

        # Apply Filter
        mask = (df["date_obj"] >= selected_range[0]) & (df["date_obj"] <= selected_range[1])
        df_filtered = df.loc[mask]
        st.info(f"Viewing **{(selected_range[1] - selected_range[0]).days} days** of history.")
    else:
        st.warning("Waiting for data...")
        df_filtered = df

# -----------------------------------------------------------------------------
# 4. MAIN TABS
# -----------------------------------------------------------------------------
tab1, tab2 = st.tabs(["📊 Global Meta Analysis", "🌍 Nation Detailed View"])

if not df_filtered.empty:
    latest_snapshot = df_filtered.sort_values("date").groupby("nation_name").tail(1)
    df = df_filtered  # Use filtered data for charts
else:
    latest_snapshot = pd.DataFrame()

# =============================================================================
# TAB 1: GLOBAL META (SPLIT VIEW)
# =============================================================================
with tab1:
    if df.empty:
        st.error("No data available.")
    else:
        # Create two columns for the side-by-side layout
        col_eco, col_mc = st.columns(2)

        # ---------------------------------------------------------
        # COLUMN 1: ECONOMIC VELOCITY
        # ---------------------------------------------------------
        with col_eco:
            st.markdown("### 📈 Economic Velocity")
            st.info("Gray = Base. **Green = Growth**. **Red = Loss**.")

            # Controls
            c_view, c_sort = st.columns(2)
            with c_view:
                view_mode = st.radio("Metric:", ["Per Capita ($)", "Total GDP ($B)", "Efficiency"], key="gdp_view")
            with c_sort:
                sort_mode = st.radio("Sort:", ["Value", "Gain ($)", "Growth (%)"], index=1, key="gdp_sort")

            show_delta_only = st.checkbox("Focus on Change", value=False, key="gdp_delta")

            # Data Prep
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

            gdp_trends["old_total_gdp"] = (gdp_trends["old_gdp_cap"] * gdp_trends["old_pop"]) / 1000
            gdp_trends["new_total_gdp"] = (gdp_trends["new_gdp_cap"] * gdp_trends["new_pop"]) / 1000

            if view_mode == "Per Capita ($)":
                gdp_trends["old_val"] = gdp_trends["old_gdp_cap"]
                gdp_trends["new_val"] = gdp_trends["new_gdp_cap"]
                axis_title = "GDP Per Capita ($)"
                fmt_fn = lambda x: f"${x:,.0f}"
            elif view_mode == "Total GDP ($B)":
                gdp_trends["old_val"] = gdp_trends["old_total_gdp"]
                gdp_trends["new_val"] = gdp_trends["new_total_gdp"]
                axis_title = "National GDP ($B)"
                fmt_fn = lambda x: f"${x/1000:.2f}T" if abs(x) >= 1000 else f"${x:,.1f}B"
            else:
                gdp_trends["old_val"] = gdp_trends["old_total_gdp"] / gdp_trends["old_cp_cost"].replace(0, 0.1)
                gdp_trends["new_val"] = gdp_trends["new_total_gdp"] / gdp_trends["new_cp_cost"].replace(0, 0.1)
                axis_title = "Yield ($B / Cap)"
                fmt_fn = lambda x: f"${x:,.1f}B"

            gdp_trends["delta"] = gdp_trends["new_val"] - gdp_trends["old_val"]
            gdp_trends["pct_change"] = (
                (gdp_trends["new_val"] - gdp_trends["old_val"]) / gdp_trends["old_val"] * 100
            ).fillna(0)
            gdp_trends["status"] = gdp_trends["delta"].apply(lambda x: "Growth" if x >= 0 else "Recession")
            gdp_trends["label"] = gdp_trends.apply(
                lambda x: f"{'+' if x['delta']>=0 else ''}{fmt_fn(x['delta'])} ({x['pct_change']:+.1f}%)", axis=1
            )

            # Sorting
            if sort_mode == "Growth (%)":
                gdp_trends = gdp_trends.sort_values("pct_change", ascending=False)
            elif sort_mode == "Gain ($)":
                gdp_trends = gdp_trends.sort_values("delta", ascending=False)
            else:
                gdp_trends = gdp_trends.sort_values("new_val", ascending=False)

            gdp_subset = gdp_trends.head(40).copy()

            # Chart
            base_gdp = alt.Chart(gdp_subset).encode(y=alt.Y("nation_name", sort=None, title=None))

            if show_delta_only:
                bar = base_gdp.mark_bar().encode(
                    x=alt.X("delta", title=f"Change in {axis_title}"),
                    color=alt.Color(
                        "status",
                        scale=alt.Scale(domain=["Growth", "Recession"], range=["#2ecc71", "#e74c3c"]),
                        legend=None,
                    ),
                    tooltip=["nation_name", "label", "delta"],
                )
                txt_pos = (
                    base_gdp.transform_filter(alt.datum.delta >= 0)
                    .mark_text(align="left", dx=5)
                    .encode(x="delta", text="label", color=alt.value("white"))
                )
                txt_neg = (
                    base_gdp.transform_filter(alt.datum.delta < 0)
                    .mark_text(align="right", dx=-5)
                    .encode(x="delta", text="label", color=alt.value("white"))
                )
                final_chart = bar + txt_pos + txt_neg
            else:
                bar_base = base_gdp.mark_bar(color="#333").encode(
                    x=alt.X("new_val", title=axis_title)
                )  # Background bar
                bar_delta = base_gdp.mark_bar().encode(
                    x="old_val",
                    x2="new_val",
                    color=alt.Color(
                        "status",
                        scale=alt.Scale(domain=["Growth", "Recession"], range=["#2ecc71", "#e74c3c"]),
                        legend=None,
                    ),
                    tooltip=["nation_name", "label", "delta"],
                )
                # Calculate anchor for text so it sits at the end of the bar
                gdp_subset["anchor"] = gdp_subset[["old_val", "new_val"]].max(axis=1)
                text = base_gdp.mark_text(align="left", dx=5).encode(x="anchor", text="label", color=alt.value("white"))
                final_chart = bar_base + bar_delta + text

            st.altair_chart(final_chart.properties(height=100 + len(gdp_subset) * 30), use_container_width=True)

        # ---------------------------------------------------------
        # COLUMN 2: MISSION CONTROL
        # ---------------------------------------------------------
        with col_mc:
            st.markdown("### 🛰️ Mission Control")
            st.info("Gray = Capacity. **Color = Built**.")

            c1, c2 = st.columns(2)
            with c1:
                show_tiny = st.checkbox("Show Tiny (Cap<=2)", value=False, key="mc_tiny")
            with c2:
                hide_capped = st.checkbox("Hide Capped", value=False, key="mc_hide")

            mc_subset = latest_snapshot.copy()
            if not show_tiny:
                mc_subset = mc_subset[(mc_subset["mc_cap"] > 2) | (mc_subset["mc_built"] > 0)]
            if hide_capped:
                mc_subset = mc_subset[mc_subset["mc_built"] < mc_subset["mc_cap"]]

            if not mc_subset.empty:
                mc_subset["status"] = mc_subset.apply(
                    lambda r: (
                        "Capped"
                        if r["mc_built"] >= r["mc_cap"]
                        else "Warning" if r["mc_utilization"] > 80 else "Building"
                    ),
                    axis=1,
                )
                mc_subset["label"] = mc_subset.apply(lambda x: f"{int(x['mc_built'])}/{int(x['mc_cap'])}", axis=1)

                base_mc = alt.Chart(mc_subset).encode(y=alt.Y("nation_name", sort="-x", title=None))

                # Stacked Bar Logic
                bg_mc = base_mc.mark_bar(color="#333").encode(x=alt.X("mc_cap", title="Slots"))
                fg_mc = base_mc.mark_bar().encode(
                    x="mc_built",
                    color=alt.Color(
                        "status",
                        scale=alt.Scale(
                            domain=["Building", "Warning", "Capped"], range=["#2ecc71", "#f1c40f", "#e74c3c"]
                        ),
                        legend=None,
                    ),
                    tooltip=["nation_name", "mc_built", "mc_cap"],
                )
                txt_mc = base_mc.mark_text(align="left", dx=5).encode(
                    x="mc_cap", text="label", color=alt.value("white")
                )

                st.altair_chart(
                    (bg_mc + fg_mc + txt_mc).properties(height=100 + len(mc_subset) * 30), use_container_width=True
                )
            else:
                st.success("All Optimized.")

        st.divider()

        # ---------------------------------------------------------
        # SCATTER PLOT (Full Width Below)
        # ---------------------------------------------------------
        st.subheader("📊 Strategic Efficiency")
        color_metric = st.radio("Color By:", ["Democracy", "Unrest", "Inequality"], index=1, horizontal=True)

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
# TAB 2: DATA DETAILS
# =============================================================================
with tab2:
    st.markdown("### 🌍 Nation Details")
    if not df.empty:
        sel_nation = st.selectbox("Select Nation:", sorted(df["nation_name"].unique()))
        st.dataframe(
            df[df["nation_name"] == sel_nation]
            .sort_values("date", ascending=False)
            .style.format({"gdp_capita": "${:,.0f}", "population_millions": "{:.1f} M", "monthly_research": "{:.1f}"}),
            use_container_width=True,
        )
