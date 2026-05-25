#!/bin/bash

REPO_DIR="/home/martin/src/games/terra-invicta"
FILE_OUTPUT="${REPO_DIR}/ai-worker/full-projectlist.txt"

# Get fixed game original project list and sort it by tech category and research cost
cat /home/martin/Games/TerraInvicta/templates/TIProjectTemplate.json | yq -r '.[] | .techCategory + "|" + .dataName + " - " + (.researchCost|tostring)' | sort > $FILE_OUTPUT

# Append custom projects to same list
cat /home/martin/src/games/terra-invicta/Mods/TIProjectTemplate.json | yq -r '.[] | .techCategory + "|" + .dataName + " - " + (.researchCost|tostring)' | sort >> $FILE_OUTPUT