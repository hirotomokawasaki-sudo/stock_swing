from pathlib import Path

from stock_swing.experiments.prompt_registry import PromptRegistry


def test_prompt_registry_hash_changes_when_text_changes(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt = prompt_dir / "p.md"
    prompt.write_text("hello", encoding="utf-8")
    first = PromptRegistry(prompt_dir).load("p.md")
    prompt.write_text("hello world", encoding="utf-8")
    second = PromptRegistry(prompt_dir).load("p.md")
    assert first.sha256 != second.sha256


def test_prompt_registry_version_defaults_to_stem(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "decision_prompt_v1.md").write_text("text", encoding="utf-8")
    spec = PromptRegistry(prompt_dir).load("decision_prompt_v1.md")
    assert spec.prompt_version == "decision_prompt_v1"
