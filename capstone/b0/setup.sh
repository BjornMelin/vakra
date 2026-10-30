set -x
mountpoint -q /scratch || mount LABEL=DOSCRATCH /scratch; mkdir -p /scratch/runs /scratch/hf
cd /scratch && [ -d vakra ] || git clone -b capstone/p0-gate https://github.com/BjornMelin/vakra.git
IMG=$(docker inspect rocm --format '{{.Config.Image}}'); docker stop rocm
cat > /scratch/runs/serve.sh <<'S'
pip install -q hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1 HF_HOME=/scratch/hf
hf download openai/gpt-oss-120b --exclude "original/*" --exclude "metal/*"
export GLOO_SOCKET_IFNAME=lo NCCL_SOCKET_IFNAME=lo VLLM_HOST_IP=127.0.0.1 HSA_NO_SCRATCH_RECLAIM=1 VLLM_ROCM_USE_AITER=1
vllm serve openai/gpt-oss-120b --served-model-name openai/gpt-oss-120b gpt-oss-120b --host 127.0.0.1 --port 8000 --tensor-parallel-size 1 --gpu-memory-utilization 0.90 --max-model-len 65536 --max-num-seqs 64 --max-num-batched-tokens 16384 --tool-call-parser openai --enable-auto-tool-choice
S
chmod +x /scratch/runs/serve.sh
docker run -d --name gptoss --network=host --ipc=host --shm-size 32G --device=/dev/kfd --device=/dev/dri --group-add video --security-opt seccomp=unconfined -v /scratch:/scratch --entrypoint /bin/bash $IMG -c "sleep infinity"
tmux new -d -s vllm "docker exec gptoss bash -lc '/scratch/runs/serve.sh 2>&1 | tee /scratch/runs/vllm_server.log'"
cd /scratch/vakra
curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH=$HOME/.local/bin:$PATH
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[init,agents]" -r requirements_benchmark.txt
(make download > /scratch/runs/download.log 2>&1; rm -rf data/test; ln -s train data/test) &
make build > /scratch/runs/build.log 2>&1
wait
docker compose up -d
sed -i 's|end_point = config.get("end_point", "https://api.groq.com/openai")|end_point = config.get("end_point", os.getenv("JUDGE_ENDPOINT", "https://api.groq.com/openai"))|' evaluator/judge.py
mkdir -p /root/vakra-internal-read-only && ln -sfn /scratch/vakra/evaluator /root/vakra-internal-read-only/evaluator
echo SETUP_DONE
