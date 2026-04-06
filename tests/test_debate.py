# tests/test_debate.py
import json
import time
from unittest.mock import MagicMock
import pytest
from scripts.debate import CACHE_TTL_SECONDS


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Redirect CACHE_PATH to tmp_path for test isolation."""
    fake_cache = tmp_path / "cross-review-models.json"
    monkeypatch.setattr("scripts.debate.CACHE_PATH", fake_cache)
    yield fake_cache


def _write_cache(cache_path, data: dict):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data))


def test_cache_hit_uses_cached_ids(isolated_cache):
    """Fresh cache (<24h) returns cached model IDs without API call."""
    _write_cache(isolated_cache, {
        "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "critic": "grok-4.20-reasoning-0309",
        "judge": "grok-4.20-multi-agent-0309"
    })
    from scripts.debate import resolve_models
    mock_client = MagicMock()
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0309"
    assert judge == "grok-4.20-multi-agent-0309"
    mock_client.models.list.assert_not_called()


def test_cache_miss_fetches_from_api(isolated_cache):
    """Missing cache triggers models.list() and caches result."""
    mock_model_reasoning = MagicMock(); mock_model_reasoning.id = "grok-4.20-reasoning-0309"
    mock_model_agent = MagicMock(); mock_model_agent.id = "grok-4.20-multi-agent-0309"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model_reasoning, mock_model_agent]
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0309"
    assert judge == "grok-4.20-multi-agent-0309"
    assert isolated_cache.exists()
    written = json.loads(isolated_cache.read_text())
    assert written["critic"] == "grok-4.20-reasoning-0309"
    assert written["judge"] == "grok-4.20-multi-agent-0309"
    assert "resolved_at" in written


def test_cache_expiry_refetches(isolated_cache):
    """Cache older than 24h is treated as miss."""
    EXPIRED_AGE_SECONDS = CACHE_TTL_SECONDS + 3600  # 1 hour past TTL
    old_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - EXPIRED_AGE_SECONDS))
    _write_cache(isolated_cache, {"resolved_at": old_time, "critic": "old-critic", "judge": "old-judge"})
    mock_model_reasoning = MagicMock(); mock_model_reasoning.id = "grok-4.20-reasoning-0415"
    mock_model_agent = MagicMock(); mock_model_agent.id = "grok-4.20-multi-agent-0415"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model_reasoning, mock_model_agent]
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0415"


def test_cache_corruption_treated_as_miss(isolated_cache):
    """Malformed JSON cache is deleted and re-fetched."""
    isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    isolated_cache.write_text("this is not json {{{{")
    mock_model_reasoning = MagicMock(); mock_model_reasoning.id = "grok-4.20-reasoning-0309"
    mock_model_agent = MagicMock(); mock_model_agent.id = "grok-4.20-multi-agent-0309"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model_reasoning, mock_model_agent]
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0309"
    written = json.loads(isolated_cache.read_text())
    assert written["critic"] == "grok-4.20-reasoning-0309"
    assert written["judge"] == "grok-4.20-multi-agent-0309"


def test_no_matching_models_exits_loudly(isolated_cache):
    """If models.list() returns nothing matching, raise SystemExit with model list."""
    mock_model = MagicMock(); mock_model.id = "some-other-model-v1"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model]
    from scripts.debate import resolve_models
    with pytest.raises(SystemExit) as exc:
        resolve_models(mock_client)
    assert exc.value.code == 1


def test_api_failure_falls_back_to_aliases(isolated_cache, capsys):
    """If models.list() raises, fall back to alias names with a warning."""
    mock_client = MagicMock()
    mock_client.models.list.side_effect = Exception("network error")
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning"
    assert judge == "grok-4.20-multi-agent"
    captured = capsys.readouterr()
    assert "Warning" in captured.err


def test_get_critique_calls_grok_reasoning(tmp_path):
    """get_critique sends content to critic model and returns text."""
    content_file = tmp_path / "content.txt"
    content_file.write_text("Here is my plan: do thing A then B.")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "Flaw: you skipped C."
    from scripts.debate import get_critique
    result = get_critique(mock_client, "grok-4.20-reasoning-0309", str(content_file), rebuttal_file=None)
    assert result == "Flaw: you skipped C."
    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs["model"] == "grok-4.20-reasoning-0309"


def test_get_critique_includes_rebuttal_in_second_round(tmp_path):
    """When rebuttal_file is provided, it's appended to the user message."""
    content_file = tmp_path / "content.txt"
    content_file.write_text("Plan A.")
    rebuttal_file = tmp_path / "rebuttal.txt"
    rebuttal_file.write_text("Claude says: A is fine because of X.")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "Still disagree."
    from scripts.debate import get_critique
    get_critique(mock_client, "grok-4.20-reasoning-0309", str(content_file), str(rebuttal_file))
    user_msg = mock_client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    assert "Claude says" in user_msg


def test_check_convergence_yes():
    """YES response → converged=False (still new objections)."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "YES"
    from scripts.debate import check_convergence
    assert check_convergence(mock_client, "grok-4.20-multi-agent-0309", "Some critique.") == False


def test_check_convergence_no():
    """NO response → converged=True."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "NO"
    from scripts.debate import check_convergence
    assert check_convergence(mock_client, "grok-4.20-multi-agent-0309", "Same old critique.") == True


def test_get_synthesis_calls_judge(tmp_path):
    """Synthesis call sends full transcript to judge model."""
    transcript_file = tmp_path / "transcript.md"
    transcript_file.write_text("# Transcript\n## Round 1 — Grok Critique\nFlaw found.")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "Final verdict: Claude was right."
    from scripts.debate import get_synthesis
    result = get_synthesis(mock_client, "grok-4.20-multi-agent-0309", str(transcript_file))
    assert result == "Final verdict: Claude was right."
    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs["model"] == "grok-4.20-multi-agent-0309"


def test_missing_api_key_exits(monkeypatch, tmp_path):
    """Missing XAI_API_KEY causes SystemExit(1) immediately."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    from scripts.debate import check_api_key
    with pytest.raises(SystemExit) as exc:
        check_api_key()
    assert exc.value.code == 1


def test_content_file_not_found_exits(monkeypatch, tmp_path):
    """Non-existent --content-file causes clean SystemExit(1) before any API call."""
    monkeypatch.setenv("XAI_API_KEY", "xai-fake-key")
    transcript_file = tmp_path / "transcript.md"
    import sys as _sys
    _sys.argv = [
        "debate.py", "--mode", "last",
        "--content-file", "/tmp/nonexistent-cr-file-xyz123.txt",
        "--source-label", "last response",
        "--transcript-file", str(transcript_file),
        "--round", "1"
    ]
    from scripts import debate as _debate
    with pytest.raises(SystemExit) as exc:
        _debate.main()
    assert exc.value.code == 1


def test_critique_emit_includes_word_count(capsys):
    """Critique JSON output includes word_count field as an integer."""
    from scripts.debate import emit
    critique_text = "This plan has three flaws. First the scope. Second the timeline. Third no error handling."
    word_count = len(critique_text.split())
    emit({"type": "critique", "round": 1, "content": critique_text, "word_count": word_count})
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["type"] == "critique"
    assert "word_count" in data
    assert isinstance(data["word_count"], int)
    assert data["word_count"] == word_count


def test_transcript_written_correctly(tmp_path):
    """Transcript file is created with correct header and round sections."""
    transcript_file = tmp_path / "transcript.md"
    from scripts.debate import init_transcript, append_transcript_section
    init_transcript(str(transcript_file), mode_label="last response",
                    critic_model="grok-4.20-reasoning-0309",
                    judge_model="grok-4.20-multi-agent-0309",
                    content="The content to review.")
    append_transcript_section(str(transcript_file), "Round 1 — Grok Critique", "Flaw found!")
    append_transcript_section(str(transcript_file), "Round 1 — Claude Rebuttal", "Flaw addressed.")
    text = transcript_file.read_text()
    assert "# Cross-Review Transcript" in text
    assert "Mode: last response" in text
    assert "grok-4.20-reasoning-0309" in text
    assert "Round 1 — Grok Critique" in text
    assert "Flaw found!" in text


def test_partial_transcript_on_api_error(tmp_path):
    """API error mid-debate appends error marker to transcript."""
    transcript_file = tmp_path / "transcript.md"
    from scripts.debate import init_transcript, append_transcript_section, append_error_to_transcript
    init_transcript(str(transcript_file), "last response", "critic", "judge", "content")
    append_transcript_section(str(transcript_file), "Round 1 — Grok Critique", "First critique.")
    append_error_to_transcript(str(transcript_file), "HTTP 429: rate limit exceeded")
    text = transcript_file.read_text()
    assert "[API ERROR: HTTP 429: rate limit exceeded]" in text


def test_convergence_emit_in_output(tmp_path, capsys):
    """After critique, convergence result is emitted as JSON line."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "NO"
    from scripts.debate import check_convergence, emit
    converged = check_convergence(mock_client, "judge-model", "A critique.")
    emit({"type": "convergence", "round": 1, "converged": converged})
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["type"] == "convergence"
    assert data["converged"] == True
