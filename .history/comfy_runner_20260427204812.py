import copy
import logging
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

LOGGER = logging.getLogger(__name__)


class WorkflowError(ValueError):
    """Raised when the workflow payload is invalid for execution."""


class ComfyExecutionError(RuntimeError):
    """Raised when ComfyUI fails to start or execute a workflow."""


class ComfyTimeoutError(TimeoutError):
    """Raised when ComfyUI execution exceeds the configured timeout."""


class ComfyRunner:
    def __init__(
        self,
        comfy_path: str = "/workspace/ComfyUI",
        host: str = "127.0.0.1",
        port: int = 8188,
        startup_timeout_seconds: int = 120,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.comfy_path = Path(comfy_path)
        self.host = host
        self.port = int(port)
        self.base_url = f"http://{self.host}:{self.port}"
        self.client_id = f"runpod-{uuid.uuid4().hex}"

        self.startup_timeout_seconds = startup_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

        self.input_dir = self.comfy_path / "input"
        self.output_dir = self.comfy_path / "output"
        self.temp_dir = self.comfy_path / "temp"

        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()

        self._process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._run_lock = threading.Lock()

    def _stream_process_logs(self, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return

        for line in process.stdout:
            LOGGER.info("ComfyUI | %s", line.rstrip())

    def _wait_until_healthy(self, timeout_seconds: int) -> None:
        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            if self._process and self._process.poll() is not None:
                raise ComfyExecutionError("ComfyUI process exited while starting.")

            try:
                response = self.session.get(f"{self.base_url}/system_stats", timeout=3)
                if response.ok:
                    return
            except requests.RequestException:
                pass

            time.sleep(1)

        raise ComfyTimeoutError("ComfyUI did not become healthy before startup timeout.")

    def _ensure_server_started(self) -> None:
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                return

            if not self.comfy_path.exists():
                raise ComfyExecutionError(f"ComfyUI path not found: {self.comfy_path}")

            command = [
                "python",
                "main.py",
                "--listen",
                self.host,
                "--port",
                str(self.port),
                "--disable-auto-launch",
                "--output-directory",
                str(self.output_dir),
            ]

            LOGGER.info("Starting ComfyUI server: %s", " ".join(command))
            self._process = subprocess.Popen(
                command,
                cwd=str(self.comfy_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            threading.Thread(
                target=self._stream_process_logs,
                args=(self._process,),
                daemon=True,
            ).start()

        self._wait_until_healthy(timeout_seconds=self.startup_timeout_seconds)

    @staticmethod
    def _is_prompt_format(workflow: Dict[str, Any]) -> bool:
        if not isinstance(workflow, dict) or not workflow:
            return False

        for key, value in workflow.items():
            if not isinstance(key, str):
                return False
            if not isinstance(value, dict):
                return False
            if "class_type" not in value:
                return False

        return True

    @staticmethod
    def _is_workflow_format(workflow: Dict[str, Any]) -> bool:
        return isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list)

    @staticmethod
    def _inject_image_into_prompt(prompt: Dict[str, Any], image_filename: str) -> int:
        load_image_count = 0

        for node in prompt.values():
            class_type = str(node.get("class_type", ""))
            if class_type.startswith("LoadImage"):
                inputs = node.setdefault("inputs", {})
                inputs["image"] = image_filename
                if "upload" in inputs:
                    inputs["upload"] = "image"
                load_image_count += 1

        if load_image_count == 0:
            raise WorkflowError("Workflow does not contain a LoadImage node.")

        return load_image_count

    @staticmethod
    def _inject_image_into_workflow(workflow: Dict[str, Any], image_filename: str) -> int:
        nodes = workflow.get("nodes", [])
        load_image_count = 0

        for node in nodes:
            node_type = str(node.get("type", ""))
            if node_type.startswith("LoadImage"):
                widgets = node.get("widgets_values")
                if isinstance(widgets, list):
                    if widgets:
                        widgets[0] = image_filename
                    else:
                        node["widgets_values"] = [image_filename]
                else:
                    node["widgets_values"] = [image_filename]
                load_image_count += 1

        if load_image_count == 0:
            raise WorkflowError("Workflow does not contain a LoadImage node.")

        return load_image_count

    @staticmethod
    def _workflow_to_prompt(workflow: Dict[str, Any]) -> Dict[str, Any]:
        nodes = workflow.get("nodes")
        links = workflow.get("links")

        if not isinstance(nodes, list):
            raise WorkflowError("Workflow JSON must contain a 'nodes' list.")
        if not isinstance(links, list):
            raise WorkflowError("Workflow JSON must contain a 'links' list for conversion.")

        nodes_by_id: Dict[int, Dict[str, Any]] = {}
        for node in nodes:
            node_id = node.get("id")
            if isinstance(node_id, int):
                nodes_by_id[node_id] = node

        link_map: Dict[int, Dict[str, int]] = {}
        for link in links:
            if not isinstance(link, list) or len(link) < 6:
                continue
            try:
                link_id = int(link[0])
                origin_id = int(link[1])
                origin_slot = int(link[2])
                target_id = int(link[3])
                target_slot = int(link[4])
            except (TypeError, ValueError):
                continue

            link_map[link_id] = {
                "origin_id": origin_id,
                "origin_slot": origin_slot,
                "target_id": target_id,
                "target_slot": target_slot,
            }

        prompt: Dict[str, Any] = {}

        for node in nodes:
            node_id = node.get("id")
            class_type = node.get("type")

            if not isinstance(node_id, int) or not isinstance(class_type, str):
                continue

            prompt_inputs: Dict[str, Any] = {}
            widget_values = node.get("widgets_values", [])
            widget_index = 0

            for node_input in node.get("inputs", []):
                if not isinstance(node_input, dict):
                    continue

                input_name = node_input.get("name")
                if not isinstance(input_name, str) or not input_name:
                    continue

                link_id = node_input.get("link")
                has_widget = isinstance(node_input.get("widget"), dict)

                widget_value = None
                if has_widget:
                    if isinstance(widget_values, list) and widget_index < len(widget_values):
                        widget_value = widget_values[widget_index]
                    widget_index += 1

                if link_id is not None:
                    try:
                        parsed_link_id = int(link_id)
                    except (TypeError, ValueError) as exc:
                        raise WorkflowError(
                            f"Invalid link id '{link_id}' on node {node_id}."
                        ) from exc

                    link_data = link_map.get(parsed_link_id)
                    if not link_data:
                        raise WorkflowError(
                            f"Missing link definition for link id {parsed_link_id}."
                        )

                    origin_node = nodes_by_id.get(link_data["origin_id"])
                    if not origin_node:
                        raise WorkflowError(
                            f"Link origin node {link_data['origin_id']} not found."
                        )

                    origin_outputs = origin_node.get("outputs", [])
                    origin_slot = link_data["origin_slot"]
                    if not isinstance(origin_outputs, list) or origin_slot >= len(origin_outputs):
                        raise WorkflowError(
                            f"Invalid origin slot {origin_slot} for node {link_data['origin_id']}."
                        )

                    origin_output = origin_outputs[origin_slot]
                    output_name = origin_output.get("name") if isinstance(origin_output, dict) else None
                    if not isinstance(output_name, str) or not output_name:
                        raise WorkflowError(
                            f"Output name missing for node {link_data['origin_id']} slot {origin_slot}."
                        )

                    prompt_inputs[input_name] = [str(link_data["origin_id"]), output_name]
                elif has_widget:
                    prompt_inputs[input_name] = widget_value

            prompt[str(node_id)] = {
                "class_type": class_type,
                "inputs": prompt_inputs,
            }

        if not prompt:
            raise WorkflowError("Unable to convert workflow JSON into ComfyUI prompt format.")

        return prompt

    def _model_exists(self, model_subdir: str, model_name: str) -> bool:
        model_dir = self.comfy_path / "models" / model_subdir
        candidate = model_dir / model_name
        if candidate.exists() and candidate.is_file():
            return True

        if not model_dir.exists() or not model_dir.is_dir():
            return False

        target = model_name.lower()
        for entry in model_dir.iterdir():
            if entry.is_file() and entry.name.lower() == target:
                return True

        return False

    def _validate_prompt_models_exist(self, prompt: Dict[str, Any]) -> None:
        model_specs = {
            "UNETLoader": ("diffusion_models", "unet_name"),
            "CLIPLoader": ("text_encoders", "clip_name"),
            "VAELoader": ("vae", "vae_name"),
            "LoraLoaderModelOnly": ("loras", "lora_name"),
        }

        missing: List[str] = []

        for node_id, node in prompt.items():
            class_type = str(node.get("class_type", ""))
            if class_type not in model_specs:
                continue

            model_subdir, input_key = model_specs[class_type]
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue

            model_name = inputs.get(input_key)
            if not isinstance(model_name, str) or not model_name.strip():
                continue

            if not self._model_exists(model_subdir=model_subdir, model_name=model_name.strip()):
                missing.append(f"models/{model_subdir}/{model_name.strip()} (node {node_id}::{class_type})")

        if missing:
            missing_joined = "; ".join(missing)
            raise WorkflowError(f"Missing required model files: {missing_joined}")

    def _validate_workflow_models_exist(self, workflow: Dict[str, Any]) -> None:
        nodes = workflow.get("nodes", [])
        if not isinstance(nodes, list):
            return

        model_specs = {
            "UNETLoader": "diffusion_models",
            "CLIPLoader": "text_encoders",
            "VAELoader": "vae",
            "LoraLoaderModelOnly": "loras",
        }

        missing: List[str] = []

        for node in nodes:
            node_type = str(node.get("type", ""))
            if node_type not in model_specs:
                continue

            widgets = node.get("widgets_values", [])
            model_name = widgets[0] if isinstance(widgets, list) and widgets else None
            if not isinstance(model_name, str) or not model_name.strip():
                continue

            model_subdir = model_specs[node_type]
            node_id = node.get("id")
            if not self._model_exists(model_subdir=model_subdir, model_name=model_name.strip()):
                missing.append(
                    f"models/{model_subdir}/{model_name.strip()} (node {node_id}::{node_type})"
                )

        if missing:
            missing_joined = "; ".join(missing)
            raise WorkflowError(f"Missing required model files: {missing_joined}")

    def _normalize_workflow(self, workflow: Dict[str, Any], image_filename: str) -> Dict[str, Any]:
        if self._is_prompt_format(workflow):
            prompt = copy.deepcopy(workflow)
            self._inject_image_into_prompt(prompt, image_filename)
            self._validate_prompt_models_exist(prompt)
            return prompt

        if self._is_workflow_format(workflow):
            workflow_copy = copy.deepcopy(workflow)
            self._inject_image_into_workflow(workflow_copy, image_filename)
            self._validate_workflow_models_exist(workflow_copy)
            return self._workflow_to_prompt(workflow_copy)

        raise WorkflowError(
            "Unsupported workflow format. Provide ComfyUI prompt JSON or graph JSON with nodes/links."
        )

    def _copy_image_to_comfy_input(self, image_path: str) -> Tuple[str, Path]:
        source = Path(image_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Input image file not found: {image_path}")

        extension = source.suffix.lower() if source.suffix else ".png"
        comfy_filename = f"runpod_{uuid.uuid4().hex}{extension}"
        destination = self.input_dir / comfy_filename

        shutil.copy2(source, destination)
        return comfy_filename, destination

    def _queue_prompt(self, prompt: Dict[str, Any]) -> str:
        payload = {
            "prompt": prompt,
            "client_id": self.client_id,
        }

        try:
            response = self.session.post(f"{self.base_url}/prompt", json=payload, timeout=30)
        except requests.RequestException as exc:
            raise ComfyExecutionError(f"Failed to queue prompt: {exc}") from exc

        if not response.ok:
            raise ComfyExecutionError(
                f"ComfyUI rejected prompt with status {response.status_code}: {response.text[:500]}"
            )

        body = response.json()
        if "error" in body:
            raise WorkflowError(f"ComfyUI validation error: {body['error']}")

        prompt_id = body.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyExecutionError("ComfyUI response did not include a prompt_id.")

        return prompt_id

    def _interrupt(self) -> None:
        try:
            self.session.post(f"{self.base_url}/interrupt", timeout=5)
        except requests.RequestException:
            LOGGER.warning("Failed to interrupt ComfyUI after timeout", exc_info=True)

    def _wait_for_completion(self, prompt_id: str, timeout_seconds: int) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            if self._process and self._process.poll() is not None:
                raise ComfyExecutionError("ComfyUI process exited during workflow execution.")

            try:
                response = self.session.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
                if response.ok:
                    history_payload = response.json()
                    if isinstance(history_payload, dict) and prompt_id in history_payload:
                        entry = history_payload[prompt_id]
                        status = entry.get("status", {}) if isinstance(entry, dict) else {}
                        status_text = status.get("status_str", "") if isinstance(status, dict) else ""

                        if status_text in {"error", "execution_error"}:
                            raise ComfyExecutionError(
                                f"ComfyUI execution failed for prompt {prompt_id}."
                            )

                        return entry
            except requests.RequestException:
                pass

            time.sleep(self.poll_interval_seconds)

        self._interrupt()
        raise ComfyTimeoutError(f"Workflow execution exceeded timeout ({timeout_seconds}s).")

    def _extract_output_image(self, history_entry: Dict[str, Any]) -> str:
        outputs = history_entry.get("outputs")
        if not isinstance(outputs, dict):
            raise ComfyExecutionError("ComfyUI history did not contain outputs.")

        candidates: List[Path] = []

        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue

            for image in node_output.get("images", []):
                if not isinstance(image, dict):
                    continue

                filename = image.get("filename")
                subfolder = image.get("subfolder", "")
                image_type = image.get("type", "output")

                if not isinstance(filename, str) or not filename:
                    continue

                if image_type == "temp":
                    base_dir = self.temp_dir
                elif image_type == "input":
                    base_dir = self.input_dir
                else:
                    base_dir = self.output_dir

                candidate = (base_dir / subfolder / filename).resolve()
                candidates.append(candidate)

        if not candidates:
            raise ComfyExecutionError("No output images found in ComfyUI history.")

        existing = [path for path in candidates if path.exists() and path.is_file()]
        if not existing:
            raise ComfyExecutionError("ComfyUI reported output images, but files were not found.")

        latest = max(existing, key=lambda path: path.stat().st_mtime)
        return str(latest)

    def run_workflow(self, image_path: str, workflow: Dict[str, Any], timeout_seconds: int) -> str:
        if not isinstance(workflow, dict):
            raise WorkflowError("Workflow payload must be a JSON object.")

        self._ensure_server_started()

        with self._run_lock:
            comfy_input_path: Path | None = None
            try:
                image_filename, comfy_input_path = self._copy_image_to_comfy_input(image_path)
                prompt = self._normalize_workflow(workflow, image_filename)
                prompt_id = self._queue_prompt(prompt)
                history_entry = self._wait_for_completion(prompt_id, timeout_seconds=timeout_seconds)
                return self._extract_output_image(history_entry)
            finally:
                if comfy_input_path and comfy_input_path.exists():
                    try:
                        comfy_input_path.unlink()
                    except OSError:
                        LOGGER.warning("Failed to cleanup temporary ComfyUI input image")
