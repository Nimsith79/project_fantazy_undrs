# Drop your private LoRA .safetensors files here before running docker build.
#
# Files placed here are automatically COPY-d into the image before
# install_models.sh runs, allowing the download step to skip them.
#
# Required files (when REQUIRE_PRIVATE_LORAS=1):
#   qwen_image_edit_remove-clothing_v1.0.safetensors
#   beuauty10.safetensors
#
# Alternatively, provide download URLs via build args:
#   --build-arg LORA_REMOVE_CLOTHING_URL=https://...
#   --build-arg LORA_BEAUTY10_URL=https://...
