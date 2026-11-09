import pytest


def test_adapter_round_trip(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("peft")
    from peft import LoraConfig, get_peft_model, get_peft_model_state_dict
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from backend.research.pilot import adapter_round_trip

    torch.manual_seed(42)
    base = Qwen3ForCausalLM(Qwen3Config(
        vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=16,
    ))
    model = get_peft_model(base, LoraConfig(r=2, target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM"))
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=0.01)
    tokens = torch.tensor([[1, 2, 3, 4, 5, 6]])
    model(input_ids=tokens, labels=tokens).loss.backward()
    optimizer.step()
    expected = {name: value.detach().clone() for name, value in get_peft_model_state_dict(model).items()}
    reloaded, result = adapter_round_trip(model, tmp_path)
    actual = get_peft_model_state_dict(reloaded)
    assert result["reload_status"] == "passed"
    assert len(result["adapter_hash"]) == 64
    assert expected.keys() == actual.keys()
    assert all(torch.equal(expected[name], actual[name]) for name in expected)


def test_low_memory_preparation_keeps_frozen_embeddings_half_precision():
    torch = pytest.importorskip("torch")
    pytest.importorskip("peft")
    from peft import LoraConfig, get_peft_model
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from backend.research.pilot import prepare_for_lora

    base = Qwen3ForCausalLM(Qwen3Config(
        vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
        num_attention_heads=2, num_key_value_heads=1, head_dim=16,
    )).half()
    prepared = prepare_for_lora(base, keep_frozen_fp16=True)
    assert prepared.get_input_embeddings().weight.dtype == torch.float16
    assert all(not parameter.requires_grad for parameter in prepared.parameters())
    model = get_peft_model(prepared, LoraConfig(r=2, target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM"))
    tokens = torch.tensor([[1, 2, 3, 4, 5, 6]])
    model(input_ids=tokens, labels=tokens).loss.backward()
    assert any(parameter.grad is not None and parameter.grad.abs().sum() > 0 for name, parameter in model.named_parameters() if "lora_" in name)


def test_optimizer_loop_reaches_updates_after_an_initial_skipped_attempt():
    torch = pytest.importorskip("torch")
    from backend.research.pilot import run_optimizer_steps

    parameter = torch.nn.Parameter(torch.tensor(0.0))
    optimizer = torch.optim.SGD([parameter], lr=0.1)

    def step(attempt):
        optimizer.zero_grad()
        loss = (parameter - 1).square()
        loss.backward()
        if attempt != 0:
            optimizer.step()
        return float(loss.detach())

    report = run_optimizer_steps(step, optimizer, target_steps=2)
    assert report["optimizer_steps"] == 2
    assert report["attempted_steps"] == 3
    assert report["skipped_steps"] == 1
    assert len(report["losses"]) == 2
    assert parameter.item() == pytest.approx(0.36)


def test_optimizer_loop_has_a_finite_limit_if_every_attempt_is_skipped():
    torch = pytest.importorskip("torch")
    from backend.research.pilot import run_optimizer_steps

    parameter = torch.nn.Parameter(torch.tensor(0.0))
    optimizer = torch.optim.SGD([parameter], lr=0.1)
    attempts = []

    def skipped_step(attempt):
        attempts.append(attempt)
        return 1.0

    with pytest.raises(RuntimeError, match="attempt limit"):
        run_optimizer_steps(skipped_step, optimizer, target_steps=2)
    assert len(attempts) == 4
    assert parameter.item() == 0
