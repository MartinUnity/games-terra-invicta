#!/bin/bash

TIEFFECT_FILE="../../Mods/TIEffectTemplate.json"

MINING_TYPES=(
    "MiningWaterBonus"
    "MiningVolatilesBonus"
    "MiningMetalsBonus"
    "MiningNoblesBonus"
    "MiningFissilesBonus"
)

# Get max-lenght based on longest mining type for better formatting
MAX_LENGTH=0
for MINING_TYPE in "${MINING_TYPES[@]}"; do
    if [[ ${#MINING_TYPE} -gt $MAX_LENGTH ]]; then
        MAX_LENGTH=${#MINING_TYPE}
    fi
done

for MINING_TYPE in "${MINING_TYPES[@]}"; do
    printf "Calculating total %-${MAX_LENGTH}s :: " "$MINING_TYPE"
    ALL_VALUES=$(cat "$TIEFFECT_FILE" | grep -i "$MINING_TYPE" -B7 | grep "value")
    TOTAL_BONUS=0
    while read -r line; do
        VALUE=$(echo "$line" | grep -oE '[0-9]+(\.[0-9]+)?')
        TOTAL_BONUS=$(echo "$TOTAL_BONUS + $VALUE" | bc)
    done <<< "$ALL_VALUES"
     echo $TOTAL_BONUS
done
