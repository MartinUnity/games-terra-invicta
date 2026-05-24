import os

# Centralized fixed workspace paths for scripts that must use repository-stored data.
# Change BASE_DIR here if you ever move the repository location.
BASE_DIR = "/home/martin/src/games/terra-invicta"

def data_path(filename: str) -> str:
    return os.path.join(BASE_DIR, filename)

# Common paths used by extraction.py and show-data.py
CAMPAIGN_HISTORY = data_path("campaign_history.csv")
CONFIG_YML = data_path("config.yml")
SAVE_DIR = data_path("terra-invicta-save/Saves")
