import logging
import os
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict

import runpod

from comfy_runner import ComfyExecutionError, ComfyRunner, ComfyTimeoutError, WorkflowError
from utils.image_utils import ImageDecodeError, decode_image_input, encode_image_to_base64

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "300"))
LOCAL_INPUT_DIR = os.getenv("LOCAL_INPUT_DIR", "/tmp/runpod_inputs")
COMFYUI_PATH = os.getenv("COMFYUI_PATH", "/workspace/ComfyUI")
COMFYUI_HOST = os.getenv("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.getenv("COMFYUI_PORT", "8188"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("runpod-handler")

Path(LOCAL_INPUT_DIR).mkdir(parents=True, exist_ok=True)

RUNNER = ComfyRunner(
    comfy_path=COMFYUI_PATH,
    host=COMFYUI_HOST,
    port=COMFYUI_PORT,
)


def _error(message: str) -> Dict[str, str]:
    return {"error": message}


def _validate_request(job: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    request_input = job.get("input")
    if not isinstance(request_input, dict):
        raise ValueError("Request must include an 'input' object.")

    image_value = request_input.get("image")
    if not isinstance(image_value, str) or not image_value.strip():
        raise ValueError("'input.image' must be a non-empty string (base64 or URL).")

    workflow = request_input.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("'input.workflow' must be a JSON object.")

    return image_value, workflow


def handler(job: Dict[str, Any]) -> Dict[str, Any]:
    request_id = uuid.uuid4().hex
    image_path = ""

    try:
        image_value, workflow = _validate_request(job)
        LOGGER.info("Request %s received", request_id)

        image_path = decode_image_input(
            image_value=image_value,
            target_dir=LOCAL_INPUT_DIR,
            prefix=f"request_{request_id}",
        )

        output_image_path = RUNNER.run_workflow(
            image_path=image_path,
            workflow=workflow,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        )

        encoded_output = encode_image_to_base64(output_image_path)
        LOGGER.info("Request %s completed successfully", request_id)

        return {
            "output": {
                "image": encoded_output,
            }
        }

    except (ValueError, ImageDecodeError, WorkflowError) as exc:
        LOGGER.warning("Request %s failed validation: %s", request_id, exc)
        return _error(str(exc))

    except ComfyTimeoutError as exc:
        LOGGER.error("Request %s timed out: %s", request_id, exc)
        return _error(str(exc))

    except ComfyExecutionError as exc:
        LOGGER.error("Request %s execution error: %s", request_id, exc)
        return _error(str(exc))

    except Exception as exc:  # pragma: no cover
        LOGGER.error("Request %s unexpected failure: %s", request_id, exc)
        LOGGER.debug("Traceback for request %s:\n%s", request_id, traceback.format_exc())
        return _error("Internal server error.")

    finally:
        if image_path:
            try:
                path = Path(image_path)
                if path.exists() and path.is_file():
                    path.unlink()
            except OSError:
                LOGGER.warning("Could not delete temporary input image for request %s", request_id)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
