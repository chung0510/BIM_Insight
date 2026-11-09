"""Standalone, offline worker executed by the user's configured AI Python."""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import threading
import time

import psutil


def verify_files(directory, manifest):
    allowed = set(manifest["files"]) | {"source-manifest.json"}
    for path in directory.iterdir():
        if path.name == ".cache" and path.is_dir():
            continue
        # Transformers prefers some extra weights/adapters/templates over the pinned files.
        if path.name not in allowed or not path.is_file():
            raise ValueError("ai_model_hash_mismatch")
    for name, expected in manifest["files"].items():
        path = directory / name
        if path.parent.resolve() != directory.resolve() or not path.is_file():
            raise ValueError("ai_model_hash_mismatch")
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                raise ValueError("ai_model_hash_mismatch")


def generate(config):
    started = time.perf_counter()
    for name, expected in config["manifest"]["packages"].items():
        if version(name) != expected:
            raise ValueError("ai_runtime_version")
    verify_files(Path(config["model_directory"]), config["manifest"])
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    if not torch.cuda.is_available():
        raise ValueError("ai_runtime_missing")
    if torch.cuda.mem_get_info()[0] < 3 * 1024 ** 3:
        raise ValueError("ai_out_of_memory")
    torch.set_num_threads(8)
    torch.manual_seed(42)
    torch.cuda.reset_peak_memory_stats()
    tokenizer = AutoTokenizer.from_pretrained(config["model_directory"], local_files_only=True, trust_remote_code=False)
    prompt = tokenizer.apply_chat_template(config["messages"], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tokenizer(prompt, return_tensors="pt")
    if inputs.input_ids.shape[1] > config["max_input_tokens"]:
        raise ValueError("ai_context_limit")
    model = AutoModelForCausalLM.from_pretrained(
        config["model_directory"], local_files_only=True, trust_remote_code=False, use_safetensors=True,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16),
        device_map={"": 0}, torch_dtype=torch.float16, attn_implementation="sdpa",
    ).eval()
    loaded = time.perf_counter()
    inputs = inputs.to("cuda")
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=config["max_new_tokens"], do_sample=False, use_cache=True, pad_token_id=tokenizer.eos_token_id)
    torch.cuda.synchronize()
    generated = output[0, inputs.input_ids.shape[1]:]
    elapsed = time.perf_counter() - loaded
    return {"text": tokenizer.decode(generated, skip_special_tokens=True), "metrics": {"weights_verified": True, "input_tokens": int(inputs.input_ids.shape[1]), "output_tokens": len(generated), "load_and_hash_seconds": loaded - started, "generation_seconds": elapsed, "elapsed_seconds": time.perf_counter() - started, "tokens_per_second": len(generated) / elapsed, "gpu_reserved_peak_bytes": torch.cuda.max_memory_reserved(), "gpu_allocated_peak_bytes": torch.cuda.max_memory_allocated(), "gpu": torch.cuda.get_device_name(0)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    parent = psutil.Process(args.parent_pid)
    def watch_parent():
        while parent.is_running():
            time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        result = generate(config)
    except Exception as error:
        codes = {"ai_model_hash_mismatch", "ai_context_limit", "ai_runtime_version", "ai_out_of_memory", "ai_runtime_missing"}
        code = str(error) if str(error) in codes else "ai_out_of_memory" if "out of memory" in str(error).lower() else "ai_runtime_missing" if isinstance(error, ImportError) else "ai_unavailable"
        result = {"error": code}
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, allow_nan=False)


if __name__ == "__main__":
    main()
