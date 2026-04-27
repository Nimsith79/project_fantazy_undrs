FROM runpod/pytorch:2.1.0-py3.10-cuda12.1.1-devel

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH=/workspace/ComfyUI \
    APP_PATH=/workspace/app \
    COMFYUI_HOST=127.0.0.1 \
    COMFYUI_PORT=8188 \
    REQUEST_TIMEOUT_SECONDS=300

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_PATH}

WORKDIR ${COMFYUI_PATH}
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR ${COMFYUI_PATH}/custom_nodes
RUN git clone https://github.com/ltdrdata/ComfyUI-Manager.git \
    && git clone https://github.com/cubiq/ComfyUI_essentials.git \
    && git clone https://github.com/evanspearman/ComfyMath.git \
    && git clone https://github.com/melMass/comfy_mtb.git \
    && git clone https://github.com/kijai/ComfyUI-KJNodes.git \
    && git clone https://github.com/TinyTerra/ComfyUI-TinyTerraNodes.git \
    && git clone https://github.com/lrzjason/Comfyui-QwenEditUtils.git

WORKDIR ${COMFYUI_PATH}
RUN if [ -f custom_nodes/ComfyUI-Manager/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/ComfyUI-Manager/requirements.txt; fi \
    && if [ -f custom_nodes/ComfyUI_essentials/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/ComfyUI_essentials/requirements.txt; fi \
    && if [ -f custom_nodes/ComfyMath/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/ComfyMath/requirements.txt; fi \
    && if [ -f custom_nodes/comfy_mtb/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/comfy_mtb/requirements.txt; fi \
    && if [ -f custom_nodes/ComfyUI-KJNodes/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/ComfyUI-KJNodes/requirements.txt; fi \
    && if [ -f custom_nodes/ComfyUI-TinyTerraNodes/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/ComfyUI-TinyTerraNodes/requirements.txt; fi \
    && if [ -f custom_nodes/Comfyui-QwenEditUtils/requirements.txt ]; then pip install --no-cache-dir -r custom_nodes/Comfyui-QwenEditUtils/requirements.txt; fi

WORKDIR ${APP_PATH}
COPY . ${APP_PATH}
RUN pip install --no-cache-dir -r ${APP_PATH}/requirements.txt
RUN chmod +x ${APP_PATH}/start.sh

# Models are expected to be baked into the image or mounted at runtime.
# No model downloads occur during handler execution.

EXPOSE 8188

CMD ["/workspace/app/start.sh"]
