#!/bin/bash
# Quick GPU status check script
# Usage: ./check_gpu_status.sh

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}GPU Status Check - 4x RTX 4090${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if metrics endpoint is available
if ! curl -s http://localhost:9400/metrics > /dev/null 2>&1; then
    echo -e "${RED}[error] Monitor not running!${NC}"
    echo "Start with: ./start_monitor.sh"
    exit 1
fi

echo -e "${GREEN}[success] Monitor is running${NC}"
echo ""

# Get metrics
METRICS=$(curl -s http://localhost:9400/metrics)

# Display GPU info
echo -e "${BLUE}GPU Status:${NC}"
echo "┌────────┬─────────────┬──────────┬──────────┬─────────┐"
echo "│  GPU   │   Memory    │   Temp   │  Power   │  Util   │"
echo "├────────┼─────────────┼──────────┼──────────┼─────────┤"

for i in 0 1 2 3; do
    # Get metrics for this GPU
    MEM_USED=$(echo "$METRICS" | grep "gpu_memory_used_bytes{gpu_index=\"$i\"" | awk '{print $2}')
    MEM_TOTAL=$(echo "$METRICS" | grep "gpu_memory_total_bytes{gpu_index=\"$i\"" | awk '{print $2}')
    TEMP=$(echo "$METRICS" | grep "gpu_temperature_celsius{gpu_index=\"$i\"" | awk '{print $2}')
    POWER=$(echo "$METRICS" | grep "gpu_power_draw_watts{gpu_index=\"$i\"" | awk '{print $2}')
    UTIL=$(echo "$METRICS" | grep "gpu_utilization_percent{gpu_index=\"$i\"" | awk '{print $2}')
    
    # Calculate memory percentage
    if [ ! -z "$MEM_USED" ] && [ ! -z "$MEM_TOTAL" ]; then
        MEM_PCT=$(echo "scale=1; $MEM_USED / $MEM_TOTAL * 100" | bc)
        MEM_USED_GB=$(echo "scale=1; $MEM_USED / 1024 / 1024 / 1024" | bc)
        MEM_TOTAL_GB=$(echo "scale=0; $MEM_TOTAL / 1024 / 1024 / 1024" | bc)
        MEM_STR="${MEM_USED_GB}/${MEM_TOTAL_GB}GB"
        
        # Color code based on usage
        if (( $(echo "$MEM_PCT > 90" | bc -l) )); then
            MEM_COLOR=$RED
        elif (( $(echo "$MEM_PCT > 75" | bc -l) )); then
            MEM_COLOR=$YELLOW
        else
            MEM_COLOR=$GREEN
        fi
        
        # Color code temperature
        if (( $(echo "$TEMP > 83" | bc -l) )); then
            TEMP_COLOR=$RED
        elif (( $(echo "$TEMP > 75" | bc -l) )); then
            TEMP_COLOR=$YELLOW
        else
            TEMP_COLOR=$GREEN
        fi
        
        # Color code power
        if (( $(echo "$POWER > 420" | bc -l) )); then
            POWER_COLOR=$RED
        elif (( $(echo "$POWER > 380" | bc -l) )); then
            POWER_COLOR=$YELLOW
        else
            POWER_COLOR=$GREEN
        fi
        
        printf "│  GPU %s │ %s%-5s (%3.0f%%)%s │ %s%6.1f°C%s │ %s%6.1fW%s │  %3.0f%%   │\n" \
            "$i" \
            "${MEM_COLOR}" "$MEM_STR" "$MEM_PCT" "${NC}" \
            "${TEMP_COLOR}" "$TEMP" "${NC}" \
            "${POWER_COLOR}" "$POWER" "${NC}" \
            "$UTIL"
    else
        echo "│  GPU $i │     N/A      │   N/A    │   N/A    │   N/A   │"
    fi
done

echo "└────────┴─────────────┴──────────┴──────────┴─────────┘"
echo ""

# Host info
echo -e "${BLUE}Host Status:${NC}"
MEM_FREE=$(echo "$METRICS" | grep "^host_memory_free_bytes " | awk '{print $2}')
MEM_TOTAL=$(echo "$METRICS" | grep "^host_memory_total_bytes " | awk '{print $2}')
CPU_PERCENT=$(echo "$METRICS" | grep "^host_cpu_percent " | awk '{print $2}')
LOAD1=$(echo "$METRICS" | grep "^host_load1 " | awk '{print $2}')

if [ ! -z "$MEM_FREE" ] && [ ! -z "$MEM_TOTAL" ]; then
    MEM_FREE_GB=$(echo "scale=1; $MEM_FREE / 1024 / 1024 / 1024" | bc)
    MEM_TOTAL_GB=$(echo "scale=0; $MEM_TOTAL / 1024 / 1024 / 1024" | bc)
    MEM_USED_GB=$(echo "scale=1; ($MEM_TOTAL - $MEM_FREE) / 1024 / 1024 / 1024" | bc)
    MEM_PCT=$(echo "scale=1; ($MEM_TOTAL - $MEM_FREE) / $MEM_TOTAL * 100" | bc)
    
    echo "  Memory: ${MEM_USED_GB}/${MEM_TOTAL_GB} GB used (${MEM_PCT}%), ${MEM_FREE_GB} GB free"
fi

if [ ! -z "$CPU_PERCENT" ]; then
    echo "  CPU Usage: ${CPU_PERCENT}%"
fi

if [ ! -z "$LOAD1" ]; then
    echo "  Load Average: ${LOAD1}"
fi

echo ""

# vLLM instances
echo -e "${BLUE}vLLM Instances:${NC}"
VLLM_RUNNING=$(echo "$METRICS" | grep "^vllm_running_requests{" | wc -l)

if [ "$VLLM_RUNNING" -gt 0 ]; then
    echo "$METRICS" | grep "^vllm_" | grep "requests{" | while read line; do
        INSTANCE=$(echo "$line" | sed 's/.*instance="\([^"]*\)".*/\1/')
        METRIC=$(echo "$line" | awk '{print $1}' | sed 's/{.*//')
        VALUE=$(echo "$line" | awk '{print $2}')
        echo "  $INSTANCE - $METRIC: $VALUE"
    done
else
    echo "  No vLLM instances detected"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo "Last updated: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

