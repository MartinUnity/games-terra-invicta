import gzip
import json
import logging as logger
import os
import time
from datetime import datetime
from threading import Timer

import pandas as pd
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# CONFIG
SAVE_DIR = "terra-invicta-save/Saves"
WATCH_DIRECTORY = "/home/martin/.steam/steam/steamapps/compatdata/1176470/pfx/drive_c/users/steamuser/Documents/My Games/TerraInvicta/Saves/"
DEBOUNCE_SECONDS = 2.0  # Wait this long after the file stops changing before reading


def fetch_latest_save():
    ## Fetch the latest save file from the directory - it is in .gz.

    # List all dirs in local dir - as it is a symlink it might point wrong:
    logger.info(f"Looking for saves in {SAVE_DIR}")

    # List all files in SAVE_DIR:
    if not os.path.isdir(SAVE_DIR):
        logger.error(f"Save directory does not exist: {SAVE_DIR}")
        raise FileNotFoundError(f"Save directory does not exist: {SAVE_DIR}")

    files = os.listdir(SAVE_DIR)
    logger.info(f"Found {len(files)} files in save directory.")

    save_files = [f for f in files if f.endswith(".gz")]
    latest_save = max(save_files, key=lambda f: os.path.getmtime(os.path.join(SAVE_DIR, f)))
    return os.path.join(SAVE_DIR, latest_save)


def load_save(path):
    # Handle GZIP or Plain JSON automatically
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8-sig") as f:
            ## Debug: print first 500 chars
            # print(f.read(500))
            # f.seek(0)
            ## Get total size of the uncompressed file and show in log:
            logger.info(f"Uncompressed file size: {f.seek(0, 2)} bytes")
            f.seek(0)
            return json.load(f)
    else:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)


def extract_nation_data(data):
    # CONFIG: The Verified Formulas
    MC_BASE_PER_REGION = 1.0  # Standard region base
    MC_GDP_DIVISOR = 290.0  # 1 MC per ~290B GDP

    root = "gamestates"
    prefix = "PavonisInteractive.TerraInvicta"

    # Handle root access safely
    if root in data:
        game_states = data[root]
    else:
        game_states = data

    # ---------------------------------------------------------
    # STEP 1: AGGREGATE REGION DATA
    # ---------------------------------------------------------
    # We loop regions FIRST to build the sums (Pop, MC Built, Region Count)
    raw_regions = game_states.get(f"{prefix}.TIRegionState", [])
    nation_geo_stats = {}

    for entry in raw_regions:
        region = entry.get("Value", entry)

        # Get Owner ID
        nation_obj = region.get("nation", {})
        nid = nation_obj.get("value")
        if nid is None:
            continue

        # Init Map if new nation
        if nid not in nation_geo_stats:
            nation_geo_stats[nid] = {"region_count": 0, "pop_millions": 0.0, "mc_built": 0.0}

        # Aggregate
        nation_geo_stats[nid]["region_count"] += 1
        nation_geo_stats[nid]["pop_millions"] += region.get("populationInMillions", 0)
        nation_geo_stats[nid]["mc_built"] += region.get("missionControl", 0)

    # ---------------------------------------------------------
    # STEP 2: EXTRACT NATION METRICS
    # ---------------------------------------------------------
    raw_nations = game_states.get(f"{prefix}.TINationState", [])
    time_entry = game_states.get(f"{prefix}.TITimeState", [])

    # Parse Date
    if time_entry:
        time_state = time_entry[0].get("Value", {})
        date_info = time_state.get("currentDateTime", {})
        current_date = datetime(date_info.get("year", 2022), date_info.get("month", 1), date_info.get("day", 1)).date()
    else:
        current_date = datetime.today().date()

    stats_list = []

    for entry in raw_nations:
        nation = entry.get("Value", entry)
        name = nation.get("displayName", "Unknown")
        nid = nation.get("ID", {}).get("value")

        # Filter: Skip Aliens and Phantom Nations (0 Regions)
        geo = nation_geo_stats.get(nid, {"region_count": 0, "pop_millions": 0.0, "mc_built": 0})
        if geo["region_count"] == 0 or name == "Alien Administration":
            continue

        # --- ECONOMY ---
        # GDP: Try "GDP" key first, fallback to older "grossDomesticProduct"
        raw_gdp = nation.get("GDP", nation.get("grossDomesticProduct", 0))
        gdp_billions = raw_gdp / 1_000_000_000

        # GDP Per Capita
        pop_millions = geo["pop_millions"]
        if pop_millions > 0:
            gdp_capita = raw_gdp / (pop_millions * 1_000_000)
        else:
            gdp_capita = 0

        # --- MISSION CONTROL (The Verified Formula) ---
        mc_built = geo["mc_built"]

        # Formula: Regions + (GDP / 290)
        # Note: We int() the GDP part because the game thresholds it.
        mc_cap_calc = int(geo["region_count"] * MC_BASE_PER_REGION + (gdp_billions / MC_GDP_DIVISOR))

        # Utilization %
        mc_utilization = (mc_built / mc_cap_calc * 100) if mc_cap_calc > 0 else 100

        # --- EFFICIENCY METRICS (The "Meta" Stats) ---
        # 1. True CP Cost (Square Root Scaling)
        # Heuristic: 1.1 * Sqrt(GDP_Billions) fits UK/USA data best
        cp_maintenance_cost = 1.1 * pow(gdp_billions, 0.5)

        # 2. Research Efficiency
        raw_research = nation.get("historyResearch", [])
        monthly_research = raw_research[0] if raw_research else 0.0

        eff_research = monthly_research / cp_maintenance_cost if cp_maintenance_cost > 0 else 0

        # 3. IP Efficiency
        base_ip = nation.get("economyScore", 0)
        eff_ip = base_ip / cp_maintenance_cost if cp_maintenance_cost > 0 else 0

        # --- FINAL DICT ---
        stats = {
            "date": current_date,
            "nation_name": name,
            "gdp_capita": round(gdp_capita, 0),
            "population_millions": round(pop_millions, 3),
            "inequality": nation.get("inequality", 0),
            "democracy": nation.get("democracy", 0),
            "unrest": nation.get("unrest", 0),
            "cohesion": nation.get("cohesion", 0),
            # The Advanced Metrics
            "monthly_research": round(monthly_research, 1),
            "monthly_ip": round(base_ip, 2),
            "cp_maintenance_cost": round(cp_maintenance_cost, 2),
            "ui_cost_per_point": round(cp_maintenance_cost / max(nation.get("numControlPoints", 1), 1), 2),
            # The Efficiency Ratios
            "efficiency_research": round(eff_research, 2),
            "efficiency_ip": round(eff_ip, 2),
            # The Validated MC Stats
            "mc_built": round(mc_built, 1),
            "mc_cap": mc_cap_calc,
            "mc_utilization": round(mc_utilization, 1),
        }
        stats_list.append(stats)

    return pd.DataFrame(stats_list)


def run_mc_calibration(data):
    print("\n--- NEW PREDICTED MC CAP (FILTERED) ---")
    print("Nation,Predicted_MC_Cap")

    # CONSTANTS (Derived from your spreadsheet data)
    MC_BASE_PER_REGION = 1.0
    MC_GDP_DIVISOR = 290.0

    root = "gamestates"
    prefix = "PavonisInteractive.TerraInvicta"

    if root in data:
        game_states = data[root]
    else:
        game_states = data

    # 1. COUNT REGIONS
    # We map Nation ID -> Region Count to identify who actually owns land.
    raw_regions = game_states.get(f"{prefix}.TIRegionState", [])
    nation_geo_stats = {}

    for entry in raw_regions:
        region = entry.get("Value", entry)

        # Get Owner
        nation_obj = region.get("nation", {})
        nid = nation_obj.get("value")
        if nid is None:
            continue

        # Init or Increment
        if nid not in nation_geo_stats:
            nation_geo_stats[nid] = 0
        nation_geo_stats[nid] += 1

    # 2. CALCULATE & PRINT
    raw_nations = game_states.get(f"{prefix}.TINationState", [])

    output_rows = []

    for entry in raw_nations:
        nation = entry.get("Value", entry)

        name = nation.get("displayName", "Unknown")
        nid = nation.get("ID", {}).get("value")

        # FILTER: Skip Aliens and Dormant Nations (Wales, Scotland, etc.)
        if name == "Alien Administration":
            continue

        region_count = nation_geo_stats.get(nid, 0)

        # THE FIX: If the nation owns 0 regions, it doesn't exist. Skip it.
        if region_count == 0:
            continue

        # B. GDP Component
        raw_gdp = nation.get("GDP", nation.get("grossDomesticProduct", 0))
        gdp_billions = raw_gdp / 1_000_000_000

        # C. The Calculation
        mc_base = region_count * MC_BASE_PER_REGION
        mc_gdp = int(gdp_billions / MC_GDP_DIVISOR)

        predicted_cap = int(mc_base + mc_gdp)

        output_rows.append((name, predicted_cap))

    # Sort alphabetically
    output_rows.sort(key=lambda x: x[0])

    for row in output_rows:
        print(f"{row[0]},{row[1]}")


class SaveWatcher(FileSystemEventHandler):
    def __init__(self):
        self.timer = None

    def on_modified(self, event):
        if event.is_directory:
            return

        # Only trigger on .gz or .json files
        if event.src_path.endswith((".gz", ".json")):
            # Logic: If a timer is already running (file is still being written), cancel it.
            if self.timer:
                self.timer.cancel()

            # Start a new timer. If no new events happen for 2 seconds, run the logic.
            self.timer = Timer(DEBOUNCE_SECONDS, self.process_event, [event.src_path])
            self.timer.start()

    def on_created(self, event):
        # Treat creation same as modification (for new manual saves)
        self.on_modified(event)

    def process_event(self, file_path):
        logger.info(f"Change detected: {file_path}. Processing...")
        run_extraction_pipeline(file_path)


def run_extraction_pipeline(specific_file_path=None):
    """
    Refactored your main logic into a function so it can be called
    both on startup and by the watcher.
    """
    try:
        # If the watcher passed a specific file, use it. Otherwise find the latest.
        if specific_file_path:
            save_path = specific_file_path
        else:
            save_path = fetch_latest_save()  # Your existing function

        logger.info(f"Loading Save: {save_path}")

        # [Error Handling] Retry logic in case file is briefly locked
        try:
            data = load_save(save_path)
        except Exception as e:
            logger.error(f"Read failed (file might be locked): {e}")
            return

        df = extract_nation_data(data)

        # Filter
        # Load nation filter from config.yml if present, otherwise fall back
        config_path = "config.yml"
        my_nations = None
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as cf:
                    cfg = yaml.safe_load(cf)
                    my_nations = cfg.get("my_nations")
                    logger.info(f"Loaded my_nations from {config_path}: {my_nations}")
            except Exception as e:
                logger.error(f"Failed to read {config_path}: {e}")
        if not my_nations:
            logger.error(f"No nations specified in {config_path}. Please add a 'my_nations' list.")
            exit(1)

        df_filtered = df[df["nation_name"].isin(my_nations)]

        # Check if empty (sometimes save files are just metadata)
        if df_filtered.empty:
            logger.warning("No nation data found. Skipping write.")
            return

        # Write to CSV
        # Note: Added checking if file exists to determine if we need a header
        file_exists = os.path.isfile("campaign_history.csv")

        # If it's a new file, write headers. If appending, don't.
        # (You might want to ensure your extract function returns consistent columns)
        df_filtered.to_csv("campaign_history.csv", mode="a", header=not file_exists, index=False)

        logger.info("Successfully updated campaign_history.csv")
        print(df_filtered.head())

        # run_mc_calibration(data)

    except Exception as e:
        logger.error(f"Pipeline crashed: {e}")


# Main
if __name__ == "__main__":
    # Initialize logging
    logger.basicConfig(level=logger.INFO, format="%(asctime)s - %(message)s")
    # 1. Run once on startup (so you don't have to wait for a save to see data)
    logger.info("Performing initial scan...")
    run_extraction_pipeline()

    # 2. Start the Watcher
    logger.info(f"Starting Watcher on: {WATCH_DIRECTORY}")

    event_handler = SaveWatcher()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIRECTORY, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher...")
        observer.stop()

    observer.join()

    # SAVE_PATH = fetch_latest_save()
    # logger.info(f"Latest save found: {SAVE_PATH}")
    # data = load_save(SAVE_PATH)
    # logger.info("Extracting nation data...")
    # logger.info(f"Data extraction lines: {len(data)}")
    # For debug - dump json into a file
    ##with open("debug_save.json", "w", encoding="utf-8") as f:
    ##    json.dump(data, f, indent=2)
    # df = extract_nation_data(data)

    # Filter for your specific nations (e.g. "Belarus", "Sweden")
    # my_nations = ["Belarus", "Sweden", "United Kingdom", "Denmark"]
    # df_filtered = df[df["nation_name"].isin(my_nations)]

    # print(df_filtered.head())

    # Optional: Append to a CSV 'database' to build history
    # df_filtered.to_csv("campaign_history.csv", mode="a", header=False)
