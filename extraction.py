import gzip
import json
import logging as logger
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
from threading import Timer

import pandas as pd
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import config

# CONFIG
# Use fixed repository paths from config.py so scripts work regardless of CWD
SAVE_DIR = config.SAVE_DIR
WATCH_DIRECTORY = "/home/martin/.steam/steam/steamapps/compatdata/1176470/pfx/drive_c/users/steamuser/Documents/My Games/TerraInvicta/Saves/"
DEBOUNCE_SECONDS = 2.0  # Wait this long after the file stops changing before reading
CONFIG_PATH = config.CONFIG_YML
CONFIG_RELOAD_INTERVAL = 60  # seconds

# Code-level default: whether to auto-persist detected `my_nations` into `config.yml`.
# This can be overridden by the `auto_persist_my_nations` key in `config.yml`.
AUTO_PERSIST_MY_NATIONS = True
# When True, write an extra log line listing each detected nation when persisting.
AUTO_PERSIST_MY_NATIONS_DEBUG = True
# Default behavior: always overwrite `config.yml` with detected `my_nations` each run.
# Can be overridden by `always_overwrite_my_nations: false` in `config.yml`.
ALWAYS_OVERWRITE_MY_NATIONS = True

# in-memory config (kept up-to-date by a watcher thread)
CURRENT_CONFIG = {}


def load_and_validate_config(path: str):
    """Load YAML config and validate expected keys. Returns dict or None on error."""
    if not os.path.isfile(path):
        logger.warning(f"Config file not found: {path}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as cf:
            cfg = yaml.safe_load(cf) or {}
    except Exception as e:
        logger.error(f"Failed to parse YAML {path}: {e}")
        return None

    # Validate: if present, 'my_nations' should be a list
    my_nations = cfg.get("my_nations")
    if my_nations is None:
        logger.warning(f"Config loaded but 'my_nations' not set in {path}")
        return cfg
    if not isinstance(my_nations, list):
        logger.error(f"Invalid config: 'my_nations' must be a list in {path}")
        return None
    return cfg


def _config_watcher_thread(path: str, interval: int):
    """Background thread: reloads config every `interval` seconds."""
    global CURRENT_CONFIG
    while True:
        cfg = load_and_validate_config(path)
        if cfg is not None:
            # if config changed, log it
            if cfg != CURRENT_CONFIG:
                logger.info(f"Config updated: {path}")
                CURRENT_CONFIG = cfg
        # sleep and loop
        time.sleep(interval)


def start_config_watcher(path: str = CONFIG_PATH, interval: int = CONFIG_RELOAD_INTERVAL):
    t = threading.Thread(target=_config_watcher_thread, args=(path, interval), daemon=True)
    t.start()


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


def detect_my_nations(data):
    """Attempt to auto-detect which nations the player controls from the save data.
    Heuristics used (authoritative-only):
    - Derive the player's faction id (via TIMetadataState match or human TIPlayerState).
    - Mark a nation as controlled if its executive/ruling fields reference that faction id.
    Only nations that actually own >=1 region are returned. This avoids fuzzy text
    searching and only detects fully-owned nations.
    Returns a list of nation display names (may be empty).
    """
    root = "gamestates"
    prefix = "PavonisInteractive.TerraInvicta"

    if root in data:
        game_states = data[root]
    else:
        game_states = data

    # Find player faction/name in metadata
    player_name = None
    meta = game_states.get(f"{prefix}.TIMetadataState", [])
    for m in meta:
        val = m.get("Value", m)
        if isinstance(val, dict) and "playerFactionName" in val:
            player_name = val.get("playerFactionName")
            break
        # some saves may use different keys
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, str) and "player" in k.lower() and "faction" in k.lower():
                    player_name = v
                    break
        if player_name:
            break

    # (We do not use top-level currentID fallback for authoritative-only detection)
    current_id = None

    raw_nations = game_states.get(f"{prefix}.TINationState", [])
    detected = []

    # Build nation -> region count map so we only return nations that actually
    # own land (this filters out absorbed or phantom entries).
    raw_regions = game_states.get(f"{prefix}.TIRegionState", [])
    nation_region_count = {}
    for rentry in raw_regions:
        r = rentry.get("Value", rentry)
        owner = r.get("nation", {})
        nid = owner.get("value")
        if nid is None:
            continue
        nation_region_count[nid] = nation_region_count.get(nid, 0) + 1

    # Attempt to find the player's faction ID from TIFactionState (case-insensitive),
    # or from TIPlayerState entries marked as human (isAI == False).
    faction_id = None
    raw_factions = game_states.get(f"{prefix}.TIFactionState", [])
    if player_name:
        for fentry in raw_factions:
            f = fentry.get("Value", fentry)
            disp = f.get("displayName")
            if isinstance(disp, str) and disp.lower() == player_name.lower():
                faction_id = f.get("ID", {}).get("value")
                break

    # If not found, look at TIPlayerState for a human player entry and use its faction
    if faction_id is None:
        raw_players = game_states.get(f"{prefix}.TIPlayerState", [])
        for pentry in raw_players:
            p = pentry.get("Value", pentry)
            # prefer explicit human player entries
            if isinstance(p, dict) and p.get("isAI") is False:
                faction_obj = p.get("faction")
                if isinstance(faction_obj, dict):
                    faction_id = faction_obj.get("value")
                    break

    for entry in raw_nations:
        nation = entry.get("Value", entry)
        name = nation.get("displayName", "Unknown")
        nid = nation.get("ID", {}).get("value")

        if name == "Alien Administration":
            continue

        # Only authoritative detection: check executive/ruling fields for faction ownership
        matched = False
        if faction_id is not None:
            lec = nation.get("lastExecutiveChange")
            if isinstance(lec, dict):
                newexec = lec.get("newExecutive")
                if isinstance(newexec, dict) and newexec.get("value") == faction_id:
                    matched = True
            ce = nation.get("currentExecutive")
            if isinstance(ce, dict) and ce.get("value") == faction_id:
                matched = True
            rf = nation.get("rulingFaction")
            if isinstance(rf, dict) and rf.get("value") == faction_id:
                matched = True

        if matched:
            # Only consider nations that actually own >=1 region
            if nation_region_count.get(nid, 0) > 0:
                detected.append(name)

    # Deduplicate and sort
    return sorted(set(detected))


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
    global CURRENT_CONFIG

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
        # Load nation filter from the in-memory CURRENT_CONFIG (kept updated by watcher)
        my_nations = CURRENT_CONFIG.get("my_nations") if isinstance(CURRENT_CONFIG, dict) else None

        # Determine overwrite + persist flags (config can override code defaults)
        always_overwrite = ALWAYS_OVERWRITE_MY_NATIONS
        auto_persist = AUTO_PERSIST_MY_NATIONS
        if isinstance(CURRENT_CONFIG, dict):
            always_overwrite = CURRENT_CONFIG.get("always_overwrite_my_nations", ALWAYS_OVERWRITE_MY_NATIONS)
            auto_persist = CURRENT_CONFIG.get("auto_persist_my_nations", AUTO_PERSIST_MY_NATIONS)

        # Decide whether to run detection: either when we don't have `my_nations`, or when
        # the policy requests an overwrite on every run.
        detected = None
        if always_overwrite or not my_nations:
            logger.info("Attempting auto-detect from save")
            detected = detect_my_nations(data)
            if detected:
                logger.info(f"Auto-detected my_nations: {detected}")
            else:
                logger.info("Auto-detection returned no nations")

        # If detection produced a list, update in-memory and persist if configured
        if detected and len(detected) > 0:
            prev = my_nations or []
            # update in-memory so subsequent runs use the detected list
            if isinstance(CURRENT_CONFIG, dict):
                CURRENT_CONFIG["my_nations"] = detected

            # Persist to config.yml (safe write with backup) if enabled in config
            try:
                if auto_persist and (always_overwrite or sorted(detected) != sorted(prev)):
                    # Determine whether to emit extra debug info for persisted nations
                    effective_debug = AUTO_PERSIST_MY_NATIONS_DEBUG
                    if isinstance(CURRENT_CONFIG, dict):
                        effective_debug = CURRENT_CONFIG.get(
                            "auto_persist_my_nations_debug", AUTO_PERSIST_MY_NATIONS_DEBUG
                        )

                    def persist_my_nations(my_nations_list, path=CONFIG_PATH):
                        """Atomically replace `path` with a minimal config containing only
                        `my_nations` (and keep a backup of the previous file).
                        This deliberately does not merge or preserve comments/old keys.
                        """
                        new_cfg = {"my_nations": my_nations_list}

                        # Write atomically: tmp -> replace, keep a backup of old
                        tmp_fd, tmp_path = tempfile.mkstemp(prefix="config-", suffix=".yml", dir=".")
                        os.close(tmp_fd)
                        try:
                            with open(tmp_path, "w", encoding="utf-8") as tf:
                                yaml.safe_dump(
                                    new_cfg, tf, default_flow_style=False, sort_keys=False, allow_unicode=True
                                )
                            if os.path.isfile(path):
                                try:
                                    shutil.copy2(path, path + ".bak")
                                except Exception:
                                    # don't fail the whole flow if backup can't be made
                                    pass
                            os.replace(tmp_path, path)
                            return True
                        finally:
                            if os.path.exists(tmp_path):
                                try:
                                    os.remove(tmp_path)
                                except Exception:
                                    pass

                    if persist_my_nations(detected, CONFIG_PATH):
                        abs_cfg = os.path.abspath(CONFIG_PATH)
                        logger.info(f"Wrote detected nations to {abs_cfg}")
                        if effective_debug:
                            logger.info(f"Persisted nations: {detected}")
                        # reload into CURRENT_CONFIG
                        cfg = load_and_validate_config(CONFIG_PATH)
                        if cfg is not None:
                            CURRENT_CONFIG = cfg
                        else:
                            # If the written file doesn't validate (race/replace oddness),
                            # force a second overwrite to ensure the minimal config lands.
                            try:
                                forced_cfg = {"my_nations": detected}
                                tmp_fd2, tmp_path2 = tempfile.mkstemp(prefix="config-force-", suffix=".yml", dir=".")
                                os.close(tmp_fd2)
                                with open(tmp_path2, "w", encoding="utf-8") as tf2:
                                    yaml.safe_dump(
                                        forced_cfg,
                                        tf2,
                                        default_flow_style=False,
                                        sort_keys=False,
                                        allow_unicode=True,
                                    )
                                os.replace(tmp_path2, CONFIG_PATH)
                                logger.info(f"Force-wrote {os.path.abspath(CONFIG_PATH)} to ensure contents")
                                cfg2 = load_and_validate_config(CONFIG_PATH)
                                if cfg2 is not None:
                                    CURRENT_CONFIG = cfg2
                            except Exception as e:
                                logger.error(f"Failed forced write of {CONFIG_PATH}: {e}")
            except Exception as e:
                logger.error(f"Failed to persist detected nations: {e}")
        else:
            # If we had no previous my_nations and detection failed, abort
            if not my_nations:
                logger.error(
                    "No valid 'my_nations' configured and auto-detection failed; skipping this extraction run."
                )
                return

        df_filtered = df[df["nation_name"].isin(my_nations)]

        # Check if empty (sometimes save files are just metadata)
        if df_filtered.empty:
            logger.warning("No nation data found. Skipping write.")
            return

        # Write to CSV in the fixed repo location
        file_exists = os.path.isfile(config.CAMPAIGN_HISTORY)

        # If it's a new file, write headers. If appending, don't.
        df_filtered.to_csv(config.CAMPAIGN_HISTORY, mode="a", header=not file_exists, index=False)

        logger.info("Successfully updated campaign_history.csv")
        print(df_filtered.head())

        # run_mc_calibration(data)

    except Exception as e:
        logger.error(f"Pipeline crashed: {e}")


# Main
if __name__ == "__main__":
    # Initialize logging
    logger.basicConfig(level=logger.INFO, format="%(asctime)s - %(message)s")
    # Load initial config and start watcher thread (so changes are picked up automatically)
    cfg = load_and_validate_config(CONFIG_PATH)
    if cfg is not None:
        CURRENT_CONFIG = cfg
    start_config_watcher(CONFIG_PATH, CONFIG_RELOAD_INTERVAL)
    # Log effective auto-persist settings and working directory to aid debugging
    try:
        effective_auto = AUTO_PERSIST_MY_NATIONS
        effective_debug = AUTO_PERSIST_MY_NATIONS_DEBUG
        if isinstance(CURRENT_CONFIG, dict):
            effective_auto = CURRENT_CONFIG.get("auto_persist_my_nations", AUTO_PERSIST_MY_NATIONS)
            effective_debug = CURRENT_CONFIG.get("auto_persist_my_nations_debug", AUTO_PERSIST_MY_NATIONS_DEBUG)
        logger.info(
            f"Auto-persist={effective_auto}, Debug={effective_debug}, CONFIG_PATH={os.path.abspath(CONFIG_PATH)}, CWD={os.getcwd()}"
        )
    except Exception:
        pass
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
