import json
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dateutil.relativedelta import relativedelta
from streamlit_autorefresh import st_autorefresh

import config

# -----------------------------------------------------------------------------
# STATE PERSISTENCE
# -----------------------------------------------------------------------------
_STATE_FILE = Path("dashboard_state.json")
_DEFAULT_STATE = {
    "gdp_n": 8,
    "mil_n": 8,
    "fund_n": 8,
    "infra_n": 8,
    "mc_n": 8,
    "row_height": 22,
}


def _load_state():
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return _DEFAULT_STATE.copy()


def _save_state():
    data = {
        "gdp_n": st.session_state.get("gdp_n", _DEFAULT_STATE["gdp_n"]),
        "mil_n": st.session_state.get("mil_n", _DEFAULT_STATE["mil_n"]),
        "fund_n": st.session_state.get("fund_n", _DEFAULT_STATE["fund_n"]),
        "infra_n": st.session_state.get("infra_n", _DEFAULT_STATE["infra_n"]),
        "mc_n": st.session_state.get("mc_n", _DEFAULT_STATE["mc_n"]),
        "row_height": st.session_state.get("row_height", _DEFAULT_STATE["row_height"]),
    }
    _STATE_FILE.write_text(json.dumps(data, indent=2))


_state = _load_state()

# -----------------------------------------------------------------------------
# 0. CUSTOM CSS
# -----------------------------------------------------------------------------
st.markdown("""
<style>
  /* Smaller widget labels in main content */
  .stApp blockquote p { font-size: 11px; }
  div[data-testid="stRadio"] label p { font-size: 11px !important; }
  div[data-testid="stCheckbox"] label p { font-size: 11px !important; }
  div[data-testid="stSlider"] p { font-size: 11px !important; }
</style>
""", unsafe_allow_html=True)

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
    "military_tech_level",
    "max_military_tech_level",
    "space_funding_year",
]


# -----------------------------------------------------------------------------
# 2. DATA LOADING
# -----------------------------------------------------------------------------
@st.cache_data(ttl=5)
def load_data():
    try:
        df = pd.read_csv(config.CAMPAIGN_HISTORY, header=None, encoding="utf-8-sig")
        # CSV has no header row; assign names to existing columns only
        num_cols = len(df.columns)
        df.columns = COL_NAMES[:num_cols]

        # Filter repeat headers (from old extraction runs)
        if "nation_name" in df.columns:
            df = df[df["nation_name"] != "nation_name"]

        # Add missing columns (e.g. military tech, space funding added after CSV existed)
        for col in COL_NAMES:
            if col not in df.columns:
                if any(x in col for x in ("military", "space")):
                    df[col] = 0
                else:
                    df[col] = None

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
            "military_tech_level",
            "max_military_tech_level",
            "space_funding_year",
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
    use_autorefresh = st.checkbox(f"📡 Live Auto-Refresh ({RELOAD_TIMESEC}s)", value=True, key="sidebar_autorefresh")
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
            index=1,
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

        st.divider()
        st.markdown("### 📏 Chart Limits")
        row_height = st.slider("Row Height (px):", 15, 45, _state.get("row_height", 22), key="row_height")
        n_gdp = st.slider("Economic Velocity:", 1, 50, _state.get("gdp_n", 8), key="gdp_n")
        n_mil = st.slider("Military Tech:", 1, 50, _state.get("mil_n", 8), key="mil_n")
        n_fund = st.slider("Space Funding:", 1, 50, _state.get("fund_n", 8), key="fund_n")
        n_infra = st.slider("Space Infra:", 1, 50, _state.get("infra_n", 8), key="infra_n")
        n_mc = st.slider("Mission Control:", 1, 50, _state.get("mc_n", 8), key="mc_n")
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
        # ---------------------------------------------------------
        # ROW 1: ECONOMIC VELOCITY + MILITARY TECH LEVEL
        # ---------------------------------------------------------
        col_eco, col_mil = st.columns(2)

        # ---------------------------------------------------------
        # COLUMN 1: ECONOMIC VELOCITY
        # ---------------------------------------------------------
        with col_eco:
            st.markdown("### 📈 Economic Velocity")
            st.info("Gray = Base. **Green = Growth**. **Red = Loss**.")

            # Controls
            c_view, c_sort = st.columns(2)
            with c_view:
                view_mode = st.radio(
                    "Metric:", ["Per Capita ($)", "Total GDP ($B)", "Efficiency"], index=1, key="gdp_view"
                )
            with c_sort:
                sort_mode = st.radio("Sort:", ["Value", "Gain ($)", "Growth (%)"], index=1, key="gdp_sort")

            show_delta_only = st.checkbox("Focus on Change", value=True, key="gdp_delta")

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

            gdp_subset = gdp_trends.head(n_gdp).copy()

            # Chart
            base_gdp = alt.Chart(gdp_subset).encode(
                y=alt.Y("nation_name", sort=None, title=None, axis=alt.Axis(labelFontSize=11))
            )

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
                    .mark_text(align="left", dx=5, fontSize=11)
                    .encode(x="delta", text="label", color=alt.value("white"))
                )
                txt_neg = (
                    base_gdp.transform_filter(alt.datum.delta < 0)
                    .mark_text(align="right", dx=-5, fontSize=11)
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
                text = base_gdp.mark_text(align="left", dx=5, fontSize=11).encode(x="anchor", text="label", color=alt.value("white"))
                final_chart = bar_base + bar_delta + text

            st.altair_chart(final_chart.properties(height=30 + len(gdp_subset) * row_height), use_container_width=True)

        # ---------------------------------------------------------
        # COLUMN 2: MILITARY TECH LEVEL
        # ---------------------------------------------------------
        with col_mil:
            st.markdown("### ⚔️ Military Tech Level")
            st.info("Gray = Max Level. **Green = Gain**. **Red = Loss**.")

            c1, c2 = st.columns(2)
            with c1:
                mil_focus_delta = st.checkbox("Focus on Change", value=False, key="mil_delta")
            with c2:
                mil_hide_capped = st.checkbox("Hide Fully Upgraded", value=True, key="mil_cap")

            mil_trends = (
                df.sort_values("date")
                .groupby("nation_name")
                .agg(
                    old_mil=("military_tech_level", "first"),
                    new_mil=("military_tech_level", "last"),
                    max_mil=("max_military_tech_level", "last"),
                )
                .reset_index()
            )

            mil_trends["delta"] = mil_trends["new_mil"] - mil_trends["old_mil"]
            mil_trends["status"] = mil_trends["delta"].apply(lambda x: "Gain" if x >= 0 else "Loss")

            def _mil_label(r):
                sign = "+" if r["delta"] >= 0 else ""
                if mil_focus_delta:
                    return f"{sign}{r['delta']:.2f}"
                return f"{r['new_mil']:.2f} / {r['max_mil']:.0f} ({sign}{r['delta']:.2f})"

            mil_trends["label"] = mil_trends.apply(_mil_label, axis=1)

            mil_subset = mil_trends[mil_trends["new_mil"] > 0].copy()
            if mil_hide_capped:
                mil_subset = mil_subset[mil_subset["new_mil"] < mil_subset["max_mil"]]
            if not mil_subset.empty:
                mil_subset = mil_subset.sort_values("new_mil" if not mil_focus_delta else "delta", ascending=False)
                mil_subset = mil_subset.head(n_mil).copy()

                base_mil = alt.Chart(mil_subset).encode(y=alt.Y("nation_name", sort=None, title=None))

                if mil_focus_delta:
                    fg_mil = base_mil.mark_bar().encode(
                        x=alt.X("delta", title="Change in Tech Level"),
                        color=alt.Color(
                            "status",
                            scale=alt.Scale(domain=["Gain", "Loss"], range=["#2ecc71", "#e74c3c"]),
                            legend=None,
                        ),
                        tooltip=["nation_name", "new_mil", "max_mil", "delta"],
                    )
                    txt_mil = base_mil.mark_text(align="right", dx=-5, fontWeight="bold").encode(
                        x="delta", text="label", color=alt.value("black")
                    )
                    final_mil = fg_mil + txt_mil
                else:
                    bg_mil = base_mil.mark_bar(color="#444").encode(x=alt.X("max_mil", title="Tech Level"))
                    fg_mil = base_mil.mark_bar().encode(
                        x="new_mil",
                        color=alt.Color(
                            "status",
                            scale=alt.Scale(domain=["Gain", "Loss"], range=["#2ecc71", "#e74c3c"]),
                            legend=None,
                        ),
                        tooltip=["nation_name", "new_mil", "max_mil", "delta"],
                    )
                    txt_mil = base_mil.mark_text(align="right", dx=-5, fontWeight="bold").encode(
                        x="new_mil", text="label", color=alt.value("black")
                    )
                    final_mil = bg_mil + fg_mil + txt_mil

                st.altair_chart(
                    final_mil.properties(height=30 + len(mil_subset) * row_height), use_container_width=True
                )
            else:
                st.info("No military tech data available.")

        st.divider()

        # ---------------------------------------------------------
        # Load space infrastructure data
        # ---------------------------------------------------------
        space_df = None
        try:
            space_df = pd.read_csv(config.SPACE_INFRA, header=None, encoding="utf-8-sig")
            space_df.columns = [
                "orbit_name", "body_name", "orbit_id",
                "pending_habs", "destroyed_assets",
                "habs_in_orbit", "fleets_in_orbit",
            ][:len(space_df.columns)]
            for col in ["pending_habs", "destroyed_assets", "habs_in_orbit", "fleets_in_orbit"]:
                if col in space_df.columns:
                    space_df[col] = pd.to_numeric(space_df[col], errors="coerce").fillna(0)
            if space_df.empty:
                space_df = None
        except Exception:
            space_df = None

        # ---------------------------------------------------------
        # ROW 2: SPACE FUNDING + SPACE INFRASTRUCTURE
        # ---------------------------------------------------------
        col_fund, col_infra = st.columns(2)

        # COLUMN 1: SPACE FUNDING
        with col_fund:
            st.markdown("### 💰 Annual Space Funding")

            if not df.empty and "space_funding_year" in latest_snapshot.columns:
                fund_subset = latest_snapshot[latest_snapshot["space_funding_year"] > 0].copy()
                if not fund_subset.empty:
                    fund_subset = fund_subset.sort_values("space_funding_year", ascending=False)
                    fund_subset["label"] = fund_subset.apply(
                        lambda x: f"${x['space_funding_year']:,.0f}M", axis=1
                    )
                    fund_subset = fund_subset.head(n_fund).copy()

                    base_fund = alt.Chart(fund_subset).encode(y=alt.Y("nation_name", sort=None, title=None))
                    bar_fund = base_fund.mark_bar().encode(
                        x=alt.X("space_funding_year", title="Annual Funding ($M)"),
                        color=alt.value("#9b59b6"),
                        tooltip=["nation_name", "space_funding_year"],
                    )
                    txt_fund = base_fund.mark_text(align="left", dx=5).encode(
                        x="space_funding_year", text="label", color=alt.value("white")
                    )

                    st.altair_chart(
                        (bar_fund + txt_fund).properties(height=30 + len(fund_subset) * row_height), use_container_width=True
                    )
                else:
                    st.info("No nations are funding space programs.")
            else:
                st.info("Space funding data unavailable.")

        # COLUMN 2: SPACE INFRASTRUCTURE
        with col_infra:
            st.markdown("### 🛸 Space Infrastructure")

            if space_df is not None and not space_df.empty:
                infra_display = space_df[
                    (space_df["habs_in_orbit"] > 0) |
                    (space_df["fleets_in_orbit"] > 0) |
                    (space_df["pending_habs"] > 0) |
                    (space_df["destroyed_assets"] > 0)
                ]
                if not infra_display.empty:
                    infra_display = infra_display.sort_values(
                        ["body_name", "orbit_name"]
                    ).reset_index(drop=True)
                    infra_display = infra_display.head(n_infra).copy()

                    rows = "".join(
                        f"<tr><td><b>{r['body_name']}</b> — {r['orbit_name']}</td>"
                        f"<td style='text-align:right'>{int(r['habs_in_orbit'])}</td>"
                        f"<td style='text-align:right'>{int(r['fleets_in_orbit'])}</td>"
                        f"<td style='text-align:right'>{int(r['pending_habs'])}</td>"
                        f"<td style='text-align:right'>{int(r['destroyed_assets'])}</td></tr>"
                        for _, r in infra_display.iterrows()
                    )
                    html = (
                        '<table style="font-size:12px; width:100%; border-collapse:collapse;">'
                        "<tr style='font-weight:bold; border-bottom:1px solid #444;'>"
                        "<td>Orbit</td><td style='text-align:right'>Habs</td>"
                        "<td style='text-align:right'>Fleets</td><td style='text-align:right'>Pending</td>"
                        "<td style='text-align:right'>Destroyed</td></tr>"
                        f"{rows}</table>"
                    )
                    st.markdown(html, unsafe_allow_html=True)
                else:
                    st.info("No space infrastructure yet.")
            else:
                st.info("Space infrastructure data unavailable.")

        st.divider()

        # ---------------------------------------------------------
        # ROW 3: MISSION CONTROL + STRATEGIC EFFICIENCY
        # ---------------------------------------------------------
        col_mc, col_eff = st.columns(2)

        # ---------------------------------------------------------
        # COLUMN 1: MISSION CONTROL
        # ---------------------------------------------------------
        with col_mc:
            st.markdown("### 🛰️ Mission Control")
            st.info("Gray = Capacity. **Color = Built**.")

            c1, c2 = st.columns(2)
            with c1:
                show_tiny = st.checkbox("Show Tiny (Cap<=2)", value=True, key="mc_tiny")
            with c2:
                hide_capped = st.checkbox("Hide Capped", value=True, key="mc_hide")

            mc_subset = latest_snapshot.copy()
            if not show_tiny:
                mc_subset = mc_subset[(mc_subset["mc_cap"] > 2) | (mc_subset["mc_built"] > 0)]
            if hide_capped:
                mc_subset = mc_subset[mc_subset["mc_built"] < mc_subset["mc_cap"]]

            if not mc_subset.empty:
                mc_subset = mc_subset.head(n_mc).copy()
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
                    (bg_mc + fg_mc + txt_mc).properties(height=30 + len(mc_subset) * row_height), use_container_width=True
                )
            else:
                st.success("All Optimized.")

        # ---------------------------------------------------------
        # COLUMN 2: STRATEGIC EFFICIENCY
        # ---------------------------------------------------------
        with col_eff:
            st.markdown("### 📊 Strategic Efficiency")
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

            st.altair_chart(c_res.properties(height=350), use_container_width=True)

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

# Persist slider state
_save_state()

