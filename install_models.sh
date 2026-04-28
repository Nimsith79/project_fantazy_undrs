#!/usr/bin/env bash
# =============================================================================
# install_models.sh — BUILD-TIME model downloader for ComfyUI
#
# This script is executed ONCE during `docker build`.
# It MUST NOT be called at container runtime (start.sh / handler.py).
#
# Environment variables expected (passed via Dockerfile ARGs → ENVs):
#   COMFYUI_PATH               — root of ComfyUI install (default: /workspace/ComfyUI)
#   HF_TOKEN                   — optional Hugging Face token for gated models
#   LORA_REMOVE_CLOTHING_URL   — URL for the remove-clothing LoRA
#   LORA_BEAUTY10_URL          — URL for the beauty-10 LoRA (may be empty/gated)
#   REQUIRE_PRIVATE_LORAS      — set to 1 to hard-fail if private LoRAs are absent
#   ALLOW_BEAUTY10_FALLBACK    — set to 1 to substitute the Lightning-8step LoRA
#                                as beuauty10.safetensors when the primary is unavailable
# =============================================================================
set -euo pipefail

COMFYUI_PATH="${COMFYUI_PATH:-/workspace/ComfyUI}"
HF_TOKEN="${HF_TOKEN:-}"
LORA_REMOVE_CLOTHING_URL="${LORA_REMOVE_CLOTHING_URL:-}"
LORA_BEAUTY10_URL="${LORA_BEAUTY10_URL:-}"
REQUIRE_PRIVATE_LORAS="${REQUIRE_PRIVATE_LORAS:-1}"
ALLOW_BEAUTY10_FALLBACK="${ALLOW_BEAUTY10_FALLBACK:-1}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# download_file <url> <output_path> [<label>]
#   Downloads <url> → <output_path> with up to 3 attempts.
#   Uses a .part temp file so a failed download never leaves a corrupt file.
#   Respects HF_TOKEN if set.
download_file() {
    local url="$1"
    local out="$2"
    local label="${3:-$(basename "$out")}"
    local tmp="${out}.part"
    local auth_args=()

    if [ -n "$HF_TOKEN" ]; then
        auth_args=(-H "Authorization: Bearer ${HF_TOKEN}")
    fi

    # Skip if already downloaded (supports --continue semantics during re-builds)
    if [ -f "$out" ]; then
        echo "[SKIP] Already present: $label"
        return 0
    fi

    echo "[DOWNLOAD] $label"
    echo "  from: $url"
    echo "  to:   $out"

    local attempt
    for attempt in 1 2 3; do
        if curl -fL \
               --retry 5 \
               --retry-delay 5 \
               --retry-all-errors \
               --connect-timeout 30 \
               --max-time 3600 \
               "${auth_args[@]}" \
               "$url" \
               -o "$tmp"; then
            mv "$tmp" "$out"
            echo "[OK] Downloaded: $label"
            return 0
        fi

        echo "[WARN] Attempt $attempt/3 failed for $label, retrying in $((attempt * 5))s..."
        rm -f "$tmp"
        sleep $((attempt * 5))
    done

    echo "[ERROR] Failed to download after 3 attempts: $label ($url)"
    exit 1
}

# download_if_missing <url> <output_path> <label> <required:0|1>
#   Like download_file but:
#   - skips silently if url is empty
#   - if required=1 and download ultimately fails → exits 1
#   - if required=0 → returns 1 on failure (caller decides)
download_if_missing() {
    local url="$1"
    local out="$2"
    local label="$3"
    local required="${4:-0}"
    local tmp="${out}.part"
    local auth_args=()

    if [ -f "$out" ]; then
        echo "[SKIP] Already present: $label"
        return 0
    fi

    if [ -z "$url" ]; then
        if [ "$required" = "1" ]; then
            echo "[ERROR] No URL configured for required model: $label"
            exit 1
        fi
        echo "[WARN] No URL configured for optional model: $label — skipping"
        return 1
    fi

    if [ -n "$HF_TOKEN" ]; then
        auth_args=(-H "Authorization: Bearer ${HF_TOKEN}")
    fi

    local attempt
    for attempt in 1 2 3; do
        local http_code
        http_code=$(curl -sSL \
                         --retry 5 \
                         --retry-delay 5 \
                         --retry-all-errors \
                         --connect-timeout 30 \
                         --max-time 3600 \
                         "${auth_args[@]}" \
                         -w "%{http_code}" \
                         "$url" \
                         -o "$tmp" || true)

        if [[ "$http_code" =~ ^2[0-9]{2}$ ]]; then
            mv "$tmp" "$out"
            echo "[OK] Downloaded: $label"
            return 0
        fi

        rm -f "$tmp"

        if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
            echo "[ERROR] Access denied (HTTP $http_code) for $label."
            echo "        If this is a gated model, accept its terms on HuggingFace and"
            echo "        pass --build-arg HF_TOKEN=<your_token> to docker build."
            if [ "$required" = "1" ]; then exit 1; fi
            return 1
        fi

        echo "[WARN] HTTP $http_code on attempt $attempt/3 for $label, retrying in $((attempt * 5))s..."
        sleep $((attempt * 5))
    done

    echo "[ERROR] Failed to download: $label after 3 attempts (last HTTP $http_code)"
    if [ "$required" = "1" ]; then exit 1; fi
    return 1
}

# ---------------------------------------------------------------------------
# Create model directories
# ---------------------------------------------------------------------------
echo "=== Creating model directories ==="
mkdir -p \
    "${COMFYUI_PATH}/models/diffusion_models" \
    "${COMFYUI_PATH}/models/text_encoders" \
    "${COMFYUI_PATH}/models/vae" \
    "${COMFYUI_PATH}/models/loras"

# ---------------------------------------------------------------------------
# Core public models
# ---------------------------------------------------------------------------
echo ""
echo "=== Downloading core models ==="

# UNET / Diffusion model (~20 GB)
download_file \
    "https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_fp8_e4m3fn.safetensors" \
    "${COMFYUI_PATH}/models/diffusion_models/qwen_image_edit_fp8_e4m3fn.safetensors" \
    "qwen_image_edit_fp8_e4m3fn.safetensors (UNET, ~20 GB)"

# Convenience symlink expected by some workflow nodes
ln -sf \
    qwen_image_edit_fp8_e4m3fn.safetensors \
    "${COMFYUI_PATH}/models/diffusion_models/Qwen-Image-Edit-2509_fp8_e4m3fn.safetensors"

# Text encoder / CLIP (~14 GB)
download_file \
    "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
    "${COMFYUI_PATH}/models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
    "qwen_2.5_vl_7b_fp8_scaled.safetensors (CLIP/text encoder, ~14 GB)"

# Convenience symlink expected by some workflow nodes
ln -sf \
    qwen_2.5_vl_7b_fp8_scaled.safetensors \
    "${COMFYUI_PATH}/models/text_encoders/qwen_2.5_vl_7b.safetensors"

# VAE (~250 MB)
download_file \
    "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" \
    "${COMFYUI_PATH}/models/vae/qwen_image_vae.safetensors" \
    "qwen_image_vae.safetensors (VAE, ~250 MB)"

# ---------------------------------------------------------------------------
# Lightning speed-up LoRAs (public)
# ---------------------------------------------------------------------------
echo ""
echo "=== Downloading Lightning LoRAs ==="

download_file \
    "https://huggingface.co/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-4steps-V1.0.safetensors" \
    "${COMFYUI_PATH}/models/loras/Qwen-Image-Lightning-4steps-V1.0.safetensors" \
    "Qwen-Image-Lightning-4steps-V1.0.safetensors"

download_file \
    "https://huggingface.co/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-8steps-V1.1.safetensors" \
    "${COMFYUI_PATH}/models/loras/Qwen-Image-Lightning-8steps-V1.1.safetensors" \
    "Qwen-Image-Lightning-8steps-V1.1.safetensors"

# ---------------------------------------------------------------------------
# Private / conditional LoRAs
# ---------------------------------------------------------------------------
echo ""
echo "=== Resolving private LoRAs ==="

REQUIRED_REMOVE_CLOTHING="${COMFYUI_PATH}/models/loras/qwen_image_edit_remove-clothing_v1.0.safetensors"
REQUIRED_BEAUTY10="${COMFYUI_PATH}/models/loras/beuauty10.safetensors"
FALLBACK_LORA="${COMFYUI_PATH}/models/loras/Qwen-Image-Lightning-8steps-V1.1.safetensors"

# remove-clothing LoRA — required
download_if_missing \
    "$LORA_REMOVE_CLOTHING_URL" \
    "$REQUIRED_REMOVE_CLOTHING" \
    "qwen_image_edit_remove-clothing_v1.0.safetensors" \
    "1"

# beauty-10 LoRA — optional with fallback
download_if_missing \
    "$LORA_BEAUTY10_URL" \
    "$REQUIRED_BEAUTY10" \
    "beuauty10.safetensors" \
    "0" || true

# Fallback: use Lightning-8step as beuauty10 when primary is unavailable
if [ ! -f "$REQUIRED_BEAUTY10" ] && [ "$ALLOW_BEAUTY10_FALLBACK" = "1" ] && [ -f "$FALLBACK_LORA" ]; then
    cp "$FALLBACK_LORA" "$REQUIRED_BEAUTY10"
    echo "[FALLBACK] Created beuauty10.safetensors from Qwen-Image-Lightning-8steps-V1.1.safetensors"
fi

# ---------------------------------------------------------------------------
# Hard validation: ensure all required models are present
# ---------------------------------------------------------------------------
echo ""
echo "=== Validating required models ==="

MISSING=0

check_model() {
    local path="$1"
    if [ ! -f "$path" ]; then
        echo "[MISSING] $path"
        MISSING=1
    else
        local size
        size=$(du -sh "$path" | cut -f1)
        echo "[OK] $path ($size)"
    fi
}

check_model "${COMFYUI_PATH}/models/diffusion_models/qwen_image_edit_fp8_e4m3fn.safetensors"
check_model "${COMFYUI_PATH}/models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
check_model "${COMFYUI_PATH}/models/vae/qwen_image_vae.safetensors"
check_model "${COMFYUI_PATH}/models/loras/Qwen-Image-Lightning-4steps-V1.0.safetensors"
check_model "${COMFYUI_PATH}/models/loras/Qwen-Image-Lightning-8steps-V1.1.safetensors"

if [ "$REQUIRE_PRIVATE_LORAS" = "1" ]; then
    check_model "$REQUIRED_REMOVE_CLOTHING"
    check_model "$REQUIRED_BEAUTY10"
fi

if [ "$MISSING" -ne 0 ]; then
    echo ""
    echo "[ERROR] One or more required models are missing. See output above."
    echo "        Provide private LoRAs via:"
    echo "          • Local files under models/loras/ in the build context, OR"
    echo "          • Build args: LORA_REMOVE_CLOTHING_URL and LORA_BEAUTY10_URL"
    exit 1
fi

echo ""
echo "=== All models verified. Build-time download complete. ==="
