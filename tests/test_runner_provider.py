import pytest
from eagle.evaluation.runner import run_synthetic_benchmark
from eagle.core.config import settings

def test_runner_requires_provider_without_explicit_classifier(monkeypatch):
    """Test (c): No classifier causes runner to request the configured real provider,
    and (d): Missing API credentials do NOT cause fallback to MockProvider.
    """
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured for the gemini provider."):
        run_synthetic_benchmark(
            "data/synthetic/gateway.csv",
            "data/synthetic/bank.csv",
            "data/synthetic/ground_truth.json"
        )
        
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "")
    
    with pytest.raises(ValueError, match="CLAUDE_API_KEY is not configured for the claude provider."):
        run_synthetic_benchmark(
            "data/synthetic/gateway.csv",
            "data/synthetic/bank.csv",
            "data/synthetic/ground_truth.json"
        )

def test_provider_selection_behavior(monkeypatch):
    """Test (e): Provider selection behavior is deterministic and testable without network calls."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
    # This should succeed since 'mock' provider doesn't require API keys in create_provider
    
    report = run_synthetic_benchmark(
        "data/synthetic/gateway.csv",
        "data/synthetic/bank.csv",
        "data/synthetic/ground_truth.json"
    )
    assert report.relationship_metrics.total_ground_truth > 0


def test_runner_llama_server_fails_without_silent_fallback(monkeypatch):
    """Test that an unavailable llama-server raises RuntimeError and does NOT silently fall back to MockProvider."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "llama_server")
    monkeypatch.setattr(settings, "LLAMA_SERVER_URL", "http://127.0.0.1:99999")
    
    with pytest.raises(RuntimeError, match="llama-server is unavailable"):
        run_synthetic_benchmark(
            "data/synthetic/gateway.csv",
            "data/synthetic/bank.csv",
            "data/synthetic/ground_truth.json"
        )

