#!/bin/bash
# Fleet Health Monitor for AWP Agents

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
YELLOW='\033[1;33m'

echo -e "${YELLOW}=== AWP Fleet Health Monitor ===${NC}"
echo "Time: $(date)"
echo "--------------------------------"

# 1. System Resources
echo -e "${GREEN}[Systems]${NC}"
free -h | awk 'NR==2{printf "RAM: %s/%s used\n", $3,$2}'
free -h | awk 'NR==3{printf "Swap: %s/%s used\n", $3,$2}'
load=$(cat /proc/loadavg | awk '{print $1}')
echo "Load Avg: $load"

# 2. Process Counts
echo ""
echo -e "${GREEN}[Processes]${NC}"
predict_count=$(ps aux | grep "predict-agent loop" | grep -v grep | wc -l)
mine_count=$(ps aux | grep "run-worker" | grep -v grep | wc -l)
echo "Predictors: $predict_count"
echo "Mine Workers: $mine_count"

# Check for duplicates
duplicates=$(ps aux | grep "run-worker" | grep -v grep | awk '{print $NF}' | sort | uniq -c | awk '$1 > 1')
if [ ! -z "$duplicates" ]; then
    echo -e "${RED}[WARN] Duplicate Miners Found:${NC}"
    echo "$duplicates"
else
    echo "No duplicate miners detected."
fi

# 3. Agent Status
echo ""
echo -e "${GREEN}[Agent Performance (Last 20 Predictions)]${NC}"
success=$(grep -a "status=filled" agents/agent-*/logs/predict.log 2>/dev/null | tail -n 20 | wc -l)
rejected=$(grep -a "REASONING_REJECTED" agents/agent-*/logs/predict.log 2>/dev/null | tail -n 20 | wc -l)
spell_fail=$(grep -a "CHALLENGE_SPELL_FAIL" agents/agent-*/logs/predict.log 2>/dev/null | tail -n 20 | wc -l)
rate_limit=$(grep -a "rate limited" agents/agent-*/logs/predict.log 2>/dev/null | tail -n 20 | wc -l)

echo "Success: $success"
echo "Reasoning Rejected: $rejected"
echo "Spell Failures: $spell_fail"
echo "Rate Limits: $rate_limit"

# 4. Detailed Status Table
echo ""
./scripts/hive.sh status | head -n 3
./scripts/hive.sh status | tail -n +4 | head -n 20
