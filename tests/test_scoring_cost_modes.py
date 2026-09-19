from __future__ import annotations

from lib.scoring import (
    ProviderScore,
    SCORE_PROFILES,
    filter_tools_by_budget,
    normalize_task_context,
)


def test_cost_profiles_have_complete_weights():
    assert set(SCORE_PROFILES) == {"economy", "balanced", "quality"}
    for weights in SCORE_PROFILES.values():
        assert sum(weights.values()) == 1.0


def test_cost_profile_changes_provider_ranking_priority():
    inexpensive = ProviderScore(
        tool_name="cheap",
        provider="local",
        task_fit=0.65,
        output_quality=0.45,
        control=0.45,
        reliability=0.75,
        cost_efficiency=0.98,
        latency=0.85,
        continuity=0.5,
        cost_profile="economy",
    )
    premium = ProviderScore(
        tool_name="premium",
        provider="cloud",
        task_fit=0.75,
        output_quality=0.98,
        control=0.92,
        reliability=0.92,
        cost_efficiency=0.20,
        latency=0.55,
        continuity=0.5,
        cost_profile="economy",
    )
    assert inexpensive.weighted_score > premium.weighted_score
    assert premium.weighted_score_for("quality") > inexpensive.weighted_score_for("quality")


def test_normalized_context_reads_cost_settings(monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_COST_PROFILE", "quality")
    monkeypatch.setenv("OPENMONTAGE_BUDGET_USD", "2.75")
    context = normalize_task_context({}, capability="video_generation")
    assert context["cost_profile"] == "quality"
    assert context["budget_usd"] == 2.75
    assert context["budget_remaining_usd"] == 2.75


class _CostTool:
    def __init__(self, cost: float):
        self.cost = cost

    def estimate_cost(self, inputs):
        return self.cost


def test_budget_filter_keeps_only_affordable_tools():
    cheap = _CostTool(0.2)
    expensive = _CostTool(2.0)
    selected = filter_tools_by_budget(
        [cheap, expensive], {}, {"budget_remaining_usd": 1.0}
    )
    assert selected == [cheap]
