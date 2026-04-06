# tests/test_debate.py
import json
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

CACHE_PATH = Path.home() / ".claude" / "cross-review-models.json"

def _write_cache(data: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data))

def _clear_cache():
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()

def test_cache_hit_uses_cached_ids(monkeypatch):
    """Fresh cache (<24h) returns cached model IDs without API call."""
    _write_cache({
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
    _clear_cache()

def test_cache_miss_fetches_from_api(monkeypatch):
    """Missing cache triggers models.list() and caches result."""
    _clear_cache()
    mock_model_reasoning = MagicMock(); mock_model_reasoning.id = "grok-4.20-reasoning-0309"
    mock_model_agent = MagicMock(); mock_model_agent.id = "grok-4.20-multi-agent-0309"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model_reasoning, mock_model_agent]
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0309"
    assert judge == "grok-4.20-multi-agent-0309"
    assert CACHE_PATH.exists()
    _clear_cache()

def test_cache_expiry_refetches(monkeypatch):
    """Cache older than 24h is treated as miss."""
    old_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 90000))
    _write_cache({"resolved_at": old_time, "critic": "old-critic", "judge": "old-judge"})
    mock_model_reasoning = MagicMock(); mock_model_reasoning.id = "grok-4.20-reasoning-0415"
    mock_model_agent = MagicMock(); mock_model_agent.id = "grok-4.20-multi-agent-0415"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model_reasoning, mock_model_agent]
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0415"
    _clear_cache()

def test_cache_corruption_treated_as_miss():
    """Malformed JSON cache is deleted and re-fetched."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text("this is not json {{{{")
    mock_model_reasoning = MagicMock(); mock_model_reasoning.id = "grok-4.20-reasoning-0309"
    mock_model_agent = MagicMock(); mock_model_agent.id = "grok-4.20-multi-agent-0309"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model_reasoning, mock_model_agent]
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning-0309"
    _clear_cache()

def test_no_matching_models_exits_loudly():
    """If models.list() returns nothing matching, raise SystemExit with model list."""
    _clear_cache()
    mock_model = MagicMock(); mock_model.id = "some-other-model-v1"
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [mock_model]
    from scripts.debate import resolve_models
    with pytest.raises(SystemExit) as exc:
        resolve_models(mock_client)
    assert exc.value.code == 1
    _clear_cache()

def test_api_failure_falls_back_to_aliases(capsys):
    """If models.list() raises, fall back to alias names with a warning."""
    _clear_cache()
    mock_client = MagicMock()
    mock_client.models.list.side_effect = Exception("network error")
    from scripts.debate import resolve_models
    critic, judge = resolve_models(mock_client)
    assert critic == "grok-4.20-reasoning"
    assert judge == "grok-4.20-multi-agent"
    captured = capsys.readouterr()
    assert "Warning" in captured.err
    _clear_cache()
