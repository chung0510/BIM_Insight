"""Bounded Qwen3-4B feasibility checks, separate from research training/evaluation."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from backend.research.hardware_probe import ResourceMonitor


def validate_config(config):
    if config.get("model_id") != "Qwen/Qwen3-4B" or not re.fullmatch(r"[a-f0-9]{40}", config.get("revision", "")):
        raise ValueError("Use the approved Qwen3-4B with a pinned revision")
    if not 20 <= config.get("max_steps", 0) <= 50 or not 256 <= config.get("context_length", 0) <= 512:
        raise ValueError("The pilot requires 20-50 optimizer steps and context 256-512")
    if not 1 <= config.get("lora_rank", 0) <= 8:
        raise ValueError("Use a low LoRA rank for this feasibility pilot")


def validate_training_result(result, expected_steps):
    if (
        result.get("optimizer_steps") != expected_steps
        or not result.get("adapter_changed")
        or result.get("reload_status") != "passed"
        or not result.get("losses")
        or not all(math.isfinite(loss) for loss in result["losses"])
        or not re.fullmatch(r"[a-f0-9]{64}", result.get("adapter_hash", ""))
    ):
        raise ValueError("Training feasibility evidence is incomplete")


def run_logged(operation, output, metadata=None):
    started = time.perf_counter()
    report = {"status": "failed", "recorded_at": datetime.now(timezone.utc).isoformat()}
    report.update(metadata or {})
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        with ResourceMonitor() as resources:
            try:
                report.update(operation())
                report["status"] = "completed"
            except Exception as error:
                report.update({
                    "status": "failed", "error_type": type(error).__name__,
                    "error_code": "out_of_memory" if isinstance(error, MemoryError) or "out of memory" in str(error).lower() else "experiment_failed",
                    "error_message": str(error)[:1500],
                })
        report["resources"] = resources.result()
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_available():
            report["resources"].update({
                "cuda_allocated_peak_bytes": torch.cuda.max_memory_allocated(),
                "cuda_reserved_peak_bytes": torch.cuda.max_memory_reserved(),
            })
        report["elapsed_seconds"] = time.perf_counter() - started
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return report


def verify_weights(config):
    directory = Path(config["model_directory"])
    for filename, expected in config["weight_files"].items():
        with (directory / filename).open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Weight hash mismatch: {filename}")


def download_model(config):
    from huggingface_hub import snapshot_download

    directory = Path(config["model_directory"])
    manifest = directory / "source-manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text(encoding="utf-8"))["revision"] != config["revision"]:
            raise ValueError("Use a separate directory for a different model revision")
    snapshot_download(
        repo_id=config["model_id"], revision=config["revision"], local_dir=directory,
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.jinja"], max_workers=2,
    )
    verify_weights(config)
    manifest.write_text(json.dumps({
        "model_id": config["model_id"], "revision": config["revision"], "weight_files": config["weight_files"],
    }, indent=2), encoding="utf-8")
    return {"model_id": config["model_id"], "revision": config["revision"], "weights_verified": True}


def load_model(config):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; do not silently change the pilot to another device/model")
    verify_weights(config)
    torch.manual_seed(config["seed"])
    torch.set_num_threads(8)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(config["model_directory"], local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(
        config["model_directory"], local_files_only=True, trust_remote_code=False,
        use_safetensors=True,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        ),
        device_map={"": 0}, torch_dtype=torch.float16, attn_implementation="sdpa",
    )
    model.config.use_cache = False
    return model, tokenizer, time.perf_counter() - started


def pilot_cases():
    # These are technical prompts without expert labels; never use them as research ground truth.
    pairs = ["ống nước–dầm", "ống gió–dầm", "máng cáp–ống gió", "ống–tường", "ống–sàn"]
    return [{
        "id": f"SMOKE-{index + 1:02}", "synthetic": True,
        "prompt": f"Tình huống thử {index + 1}: {pairs[index % len(pairs)]}. Chưa có hình học, số đo hay bản vẽ đã xác minh. Trả JSON missing_data và requires_review; không kết luận đã có xung đột.",
        "response": '{"missing_data":["verified_geometry","measurements"],"requires_review":true}',
    } for index in range(10)]


def inference(config):
    import torch

    model, tokenizer, load_seconds = load_model(config)
    model.eval()
    results = []
    for case in pilot_cases():
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": case["prompt"]}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=config["context_length"]).to("cuda")
        started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=config["max_new_tokens"], do_sample=False, use_cache=True)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        generated = output[0, inputs.input_ids.shape[1]:]
        text = tokenizer.decode(generated, skip_special_tokens=True)
        results.append({"id": case["id"], "seconds": elapsed, "generated_tokens": len(generated), "text": text})
        print(f"Inference {len(results)}/10: {elapsed:.2f}s", flush=True)
    total_time = sum(item["seconds"] for item in results)
    return {
        "model_id": config["model_id"], "revision": config["revision"], "load_seconds": load_seconds,
        "purpose": "technical_smoke_only", "expert_accuracy": "not_evaluated", "cases": results,
        "tokens_per_second": sum(item["generated_tokens"] for item in results) / total_time,
    }


def adapter_round_trip(model, directory):
    import torch
    from peft import PeftModel, get_peft_model_state_dict

    before = {key: value.detach().cpu().clone() for key, value in get_peft_model_state_dict(model).items()}
    model.save_pretrained(directory, safe_serialization=True)
    reloaded = PeftModel.from_pretrained(model.unload(), directory, is_trainable=False)
    after = get_peft_model_state_dict(reloaded)
    if before.keys() != after.keys() or not all(torch.equal(before[key], after[key].detach().cpu()) for key in before):
        raise ValueError("Reloaded adapter differs from the trained adapter")
    with (Path(directory) / "adapter_model.safetensors").open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return reloaded, {"reload_status": "passed", "adapter_hash": digest}


def prepare_for_lora(model, keep_frozen_fp16=False):
    from peft import prepare_model_for_kbit_training

    if not keep_frozen_fp16:
        return prepare_model_for_kbit_training(model, gradient_checkpointing_kwargs={"use_reentrant": False})
    # The large frozen embedding/head must stay fp16 to avoid inflating laptop VRAM.
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    return model


def run_optimizer_steps(step, optimizer, target_steps):
    updates = []
    losses = []
    hook = optimizer.register_step_post_hook(lambda *_args: updates.append(1))
    try:
        for attempt in range(target_steps * 2):
            previous = len(updates)
            loss = step(attempt)
            if not math.isfinite(loss):
                raise ValueError("Non-finite training loss")
            if len(updates) > previous:
                losses.append(loss)
            print(f"Attempt {attempt + 1}: optimizer_steps={len(updates)}/{target_steps}, loss={loss:.5f}", flush=True)
            if len(updates) == target_steps:
                return {
                    "optimizer_steps": len(updates), "attempted_steps": attempt + 1,
                    "skipped_steps": attempt + 1 - len(updates), "losses": losses,
                }
    finally:
        hook.remove()
    raise RuntimeError("Optimizer attempt limit reached before the required updates")


def train(config, directory):
    import torch
    from peft import LoraConfig, get_peft_model, get_peft_model_state_dict

    if Path(directory).exists():
        raise FileExistsError("Use a new adapter directory for each pilot attempt")
    model, tokenizer, load_seconds = load_model(config)
    model = prepare_for_lora(model, keep_frozen_fp16=config.get("keep_frozen_fp16", False))
    model = get_peft_model(model, LoraConfig(
        r=config["lora_rank"], lora_alpha=config["lora_rank"] * 2,
        target_modules=["q_proj", "v_proj"], lora_dropout=0, task_type="CAUSAL_LM",
    ))
    model.train()
    before = {key: value.detach().cpu().clone() for key, value in get_peft_model_state_dict(model).items()}
    optimizer = torch.optim.AdamW([parameter for parameter in model.parameters() if parameter.requires_grad], lr=config["learning_rate"])
    scaler = torch.amp.GradScaler("cuda")
    cases = pilot_cases()
    started = time.perf_counter()

    def step(attempt):
        case = cases[attempt % len(cases)]
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": case["prompt"]}, {"role": "assistant", "content": case["response"]}],
            tokenize=False, enable_thinking=False,
        )
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=config["context_length"]).to("cuda")
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.float16):
            loss = model(**inputs, labels=inputs.input_ids).loss
        if not torch.isfinite(loss):
            raise ValueError("Non-finite training loss")
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        return float(loss.detach())

    progress = run_optimizer_steps(step, optimizer, config["max_steps"])
    torch.cuda.synchronize()
    train_seconds = time.perf_counter() - started
    after = get_peft_model_state_dict(model)
    changed = any(not torch.equal(before[key], after[key].detach().cpu()) for key in before)
    _reloaded, saved = adapter_round_trip(model, directory)
    result = {
        "model_id": config["model_id"], "revision": config["revision"], "config": config,
        "purpose": "technical_smoke_only_not_expert_labelled_training", "expert_accuracy": "not_evaluated",
        **progress, "adapter_changed": changed,
        "load_seconds": load_seconds, "train_seconds": train_seconds,
        "steps_per_second": progress["optimizer_steps"] / train_seconds, **saved,
    }
    validate_training_result(result, config["max_steps"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["download", "inference", "train"])
    parser.add_argument("--config", type=Path, default=Path("backend/research/configs/pilot.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter-dir", type=Path, default=Path("data/adapters/pilot-1"))
    args = parser.parse_args()
    if args.output.resolve() == args.config.resolve() or args.output.suffix.lower() != ".json":
        parser.error("Write a JSON report to a path separate from the configuration")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ.setdefault("HF_HOME", str(Path("data/cache/huggingface").resolve()))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(config)
    if any(args.output.resolve().is_relative_to(path.resolve()) for path in [Path(config["model_directory"]), args.adapter_dir]):
        parser.error("Reports must not overwrite model or adapter files")
    operations = {"download": lambda: download_model(config), "inference": lambda: inference(config), "train": lambda: train(config, args.adapter_dir)}
    try:
        report = run_logged(operations[args.mode], args.output, metadata={
            "mode": args.mode, "config": config,
            "dataset_hash": hashlib.sha256(json.dumps(pilot_cases(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        })
    except FileExistsError:
        parser.error("Report path already exists; choose a new .json path")
    print(json.dumps({key: report[key] for key in ["status", "elapsed_seconds"]}), flush=True)
    raise SystemExit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
