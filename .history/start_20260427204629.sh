#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

COMFYUI_PATH="${COMFYUI_PATH:-/workspace/ComfyUI}"
MODEL_MOUNT_PATH="${MODEL_MOUNT_PATH:-/runpod-volume/comfy-models}"

link_model_files() {
	local source_dir="$1"
	local target_dir="$2"

	mkdir -p "$target_dir"
	if [ ! -d "$source_dir" ]; then
		return 0
	fi

	shopt -s nullglob
	for model_path in "$source_dir"/*; do
		local model_name
		model_name="$(basename "$model_path")"
		ln -sfn "$model_path" "$target_dir/$model_name"
	done
	shopt -u nullglob
}

link_model_files "$MODEL_MOUNT_PATH/diffusion_models" "$COMFYUI_PATH/models/diffusion_models"
link_model_files "$MODEL_MOUNT_PATH/text_encoders" "$COMFYUI_PATH/models/text_encoders"
link_model_files "$MODEL_MOUNT_PATH/vae" "$COMFYUI_PATH/models/vae"
link_model_files "$MODEL_MOUNT_PATH/loras" "$COMFYUI_PATH/models/loras"

cd /workspace/app
exec python -u handler.py
