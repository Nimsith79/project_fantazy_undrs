# =============================================================================
# RunPod Serverless — ComfyUI (Qwen Image Edit)
#
# Build strategy: all model downloads happen at IMAGE BUILD TIME via
# install_models.sh.  The running container performs ZERO network downloads.
#
# Build args
# ----------
# INSTALL_MODELS          — set to 0 to skip model downloads (dev/CI builds)
# HF_TOKEN                — Hugging Face token for gated models
# LORA_REMOVE_CLOTHING_URL — URL for the remove-clothing LoRA (required)
# LORA_BEAUTY10_URL       — URL for the beauty-10 LoRA (optional; fallback available)
# REQUIRE_PRIVATE_LORAS   — 1 = fail build if private LoRAs are absent (default: 1)
# ALLOW_BEAUTY10_FALLBACK — 1 = substitute Lightning-8step LoRA as beuauty10 (default: 1)
#
# Example build
# -------------
#   docker build \
#     --build-arg HF_TOKEN=hf_xxx \
#     --build-arg LORA_REMOVE_CLOTHING_URL=https://... \
#     --build-arg LORA_BEAUTY10_URL=https://... \
#     -t my-comfyui:latest .
# =============================================================================

FROM runpod/pytorch:1.0.3-cu1290-torch260-ubuntu2204

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH=/workspace/ComfyUI \
    APP_PATH=/workspace/app \
    COMFYUI_HOST=127.0.0.1 \
    COMFYUI_PORT=8188 \
    REQUEST_TIMEOUT_SECONDS=300

# ---------------------------------------------------------------------------
# Build-time arguments (forwarded to install_models.sh via ENV)
# ---------------------------------------------------------------------------
ARG INSTALL_MODELS=1
ARG HF_TOKEN=
ARG LORA_REMOVE_CLOTHING_URL=https://huggingface.co/TomaOmito/Qwen-Edit-2509-Lora-Remove-Clothing/resolve/main/remove_clothing.safetensors
ARG LORA_BEAUTY10_URL=https://huggingface.co/miaaiart/simply-beauty-10/resolve/main/simply-beauty-10.safetensors
ARG REQUIRE_PRIVATE_LORAS=1
ARG ALLOW_BEAUTY10_FALLBACK=1

# Make ARGs visible inside RUN shells (needed by install_models.sh)
ENV INSTALL_MODELS=${INSTALL_MODELS} \
    HF_TOKEN=${HF_TOKEN} \
    LORA_REMOVE_CLOTHING_URL=${LORA_REMOVE_CLOTHING_URL} \
    LORA_BEAUTY10_URL=${LORA_BEAUTY10_URL} \
    REQUIRE_PRIVATE_LORAS=${REQUIRE_PRIVATE_LORAS} \
    ALLOW_BEAUTY10_FALLBACK=${ALLOW_BEAUTY10_FALLBACK}

WORKDIR /workspace

# ---------------------------------------------------------------------------
# 1. System dependencies
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        wget \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. ComfyUI core
# ---------------------------------------------------------------------------
RUN git clone https://github.com/comfyanonymous/ComfyUI.git "${COMFYUI_PATH}"

WORKDIR ${COMFYUI_PATH}
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# 3. Custom nodes
# ---------------------------------------------------------------------------
WORKDIR ${COMFYUI_PATH}/custom_nodes

RUN set -eux; \
    clone_repo() { \
        local repo_url="$1"; \
        local target_dir="$2"; \
        if [ -d "$target_dir/.git" ]; then \
            echo "Repository already exists: $target_dir"; \
            return 0; \
        fi; \
        for attempt in 1 2 3; do \
            if git clone --depth 1 "$repo_url" "$target_dir"; then \
                return 0; \
            fi; \
            echo "Clone failed for $repo_url (attempt $attempt/3), retrying..."; \
            rm -rf "$target_dir"; \
            sleep $((attempt * 3)); \
        done; \
        echo "Failed to clone repository after retries: $repo_url"; \
        exit 1; \
    }; \
    clone_repo https://github.com/ltdrdata/ComfyUI-Manager.git          ComfyUI-Manager; \
    clone_repo https://github.com/cubiq/ComfyUI_essentials.git          ComfyUI_essentials; \
    clone_repo https://github.com/evanspearman/ComfyMath.git            ComfyMath; \
    clone_repo https://github.com/melMass/comfy_mtb.git                 comfy_mtb; \
    clone_repo https://github.com/kijai/ComfyUI-KJNodes.git             ComfyUI-KJNodes; \
    clone_repo https://github.com/TinyTerra/ComfyUI_tinyterraNodes.git  ComfyUI-TinyTerraNodes; \
    clone_repo https://github.com/lrzjason/Comfyui-QwenEditUtils.git    Comfyui-QwenEditUtils

WORKDIR ${COMFYUI_PATH}

RUN for req in \
        custom_nodes/ComfyUI-Manager/requirements.txt \
        custom_nodes/ComfyUI_essentials/requirements.txt \
        custom_nodes/ComfyMath/requirements.txt \
        custom_nodes/comfy_mtb/requirements.txt \
        custom_nodes/ComfyUI-KJNodes/requirements.txt \
        custom_nodes/ComfyUI-TinyTerraNodes/requirements.txt \
        custom_nodes/Comfyui-QwenEditUtils/requirements.txt; \
    do \
        if [ -f "$req" ]; then \
            pip install --no-cache-dir -r "$req"; \
        fi; \
    done

# ---------------------------------------------------------------------------
# 4. Download ALL models at build time
#    Pass INSTALL_MODELS=0 to skip (e.g. lightweight CI/dev builds).
#    Private LoRAs can be supplied via:
#      • Local files under models/loras/ in the build context, OR
#      • Build args: LORA_REMOVE_CLOTHING_URL / LORA_BEAUTY10_URL
# ---------------------------------------------------------------------------
COPY install_models.sh /workspace/install_models.sh
RUN chmod +x /workspace/install_models.sh

# Copy any locally-present private LoRA files into the image BEFORE the
# download script runs, so download_if_missing() can skip them.
COPY models/loras/ ${COMFYUI_PATH}/models/loras/

RUN if [ "${INSTALL_MODELS}" = "1" ]; then \
        /workspace/install_models.sh; \
    else \
        echo "[INFO] INSTALL_MODELS=0 — skipping model downloads."; \
    fi

# ---------------------------------------------------------------------------
# 5. Application code
# ---------------------------------------------------------------------------
WORKDIR ${APP_PATH}
COPY . ${APP_PATH}/
RUN pip install --no-cache-dir -r ${APP_PATH}/requirements.txt
RUN chmod +x ${APP_PATH}/start.sh

# ---------------------------------------------------------------------------
# 6. Expose & launch
#    Runtime behaviour: start ComfyUI server and serve the RunPod handler.
#    NO downloads happen here.
# ---------------------------------------------------------------------------
EXPOSE 8188

CMD ["/workspace/app/start.sh"]
