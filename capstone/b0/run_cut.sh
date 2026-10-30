cd /scratch/vakra && source .venv/bin/activate
export LITELLM_BASE_URL=http://localhost:8000/v1 LITELLM_API_KEY=dummy JUDGE_BACKEND=groq JUDGE_ENDPOINT=http://localhost:8000 API_KEY=dummy
unset LITELLM_EXTRA_BODY
N=${N:-2}; SHARDS=${SHARDS:-8}; RUN=/scratch/runs/b0_$(date +%H%M); mkdir -p $RUN/eval
echo $RUN > /scratch/runs/LATEST; git rev-parse --short HEAD > $RUN/commit.txt; date +%s > $RUN/start_epoch
declare -A DIRS=([1]=capability_1_bi_apis [2]=capability_2_dashboard_apis [3]=capability_3_multihop_reasoning [4]=capability_4_multiturn)
for C in 1 2 3 4; do
  mapfile -t DOMS < <(ls data/train/${DIRS[$C]}/input/*.json | xargs -n1 basename | sed 's/\.json$//' | sort)
  for s in $(seq 0 $((SHARDS-1))); do
    ARGS=(); for i in "${!DOMS[@]}"; do [ $((i % SHARDS)) -eq $s ] && ARGS+=(--domain "${DOMS[$i]}"); done
    [ ${#ARGS[@]} -eq 0 ] && continue
    timeout ${TMO:-1200} python benchmark_runner.py --capability_id $C "${ARGS[@]}" --max-samples-per-domain $N --provider litellm --model gpt-oss-120b --temperature 0.0 --output $RUN/cap$C > $RUN/cap${C}_s$s.log 2>&1 &
  done
done
wait
date +%s > $RUN/end_epoch
declare -A NAMES=([1]=capability_bi_apis [2]=capability_dashboard_apis [3]=capability_multihop_reasoning [4]=capability_multiturn)
for C in 1 2 3 4; do
  python evaluator/evaluator.py --capability_name ${NAMES[$C]} --gt_root data/train/${DIRS[$C]}/output --pred_root $RUN/cap$C --output $RUN/eval/cap$C.json --mcp-config benchmark/mcp_connection_config.yaml > $RUN/eval/cap$C.log 2>&1 &
done
wait
python - <<PY
import json,glob,os
for f in sorted(glob.glob("$RUN/eval/cap*.json")):
    d=json.load(open(f)); s=d.get("summary",d)
    print(os.path.basename(f), {k:s.get(k) for k in ("num_samples","num_correct","mean_dialogue_score")})
PY
echo RUN_DONE $RUN
