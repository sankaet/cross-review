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
