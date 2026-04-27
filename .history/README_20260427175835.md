# RunPod Serverless ComfyUI Endpoint

This repository runs ComfyUI headlessly inside a RunPod Serverless worker and executes workflows dynamically per request.

## Features

- Accepts input image as base64 or URL.
- Accepts workflow JSON per request.
- Supports both ComfyUI prompt format and graph workflow format.
- Auto-injects uploaded image into every `LoadImage` node.
- Runs ComfyUI in a persistent process so models stay loaded across requests.
- Returns the latest generated output image as base64.
- Structured error responses and timeout handling.

## Request Contract

```json
{
  "input": {
    "image": "<base64-or-http-url>",
    "workflow": { "...": "..." }
  }
}
```

## Success Response

```json
{
  "output": {
    "image": "<base64>"
  }
}
```

## Error Response

```json
{
  "error": "message"
}
```

## Files

- `Dockerfile`: Runtime image with ComfyUI and custom nodes.
- `handler.py`: RunPod serverless handler.
- `comfy_runner.py`: ComfyUI lifecycle, workflow conversion/injection, execution, polling.
- `utils/image_utils.py`: base64/URL decoding and output encoding.
- `workflow_template.json`: minimal runnable workflow example.
- `start.sh`: entrypoint script.
- `requirements.txt`: Python dependencies for the handler.

## Build

```bash
docker build -t runpod-comfy-serverless:latest .
```

## Runtime Notes

- Models are not downloaded during request handling.
- Ensure required models are baked into the image or mounted into ComfyUI models directories.
- ComfyUI custom nodes included here are based on your `requried models and nodes.txt` list.

## Local Smoke Test Payload

Use your current workflow file `【NSFW】remove+clothes+in+image.json` as the request `input.workflow` value.
