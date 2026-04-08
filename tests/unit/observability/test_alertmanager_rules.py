"""
Unit tests for AlertManager rules template — issue #45.

TDD red phase: these tests define the acceptance criteria and must
run before the artefacts are created.

Acceptance Criteria (from issue #45):
- docs/monitoring/alertmanager-rules.yml exists and is valid YAML
- Required alert rules present: SagazCompensationRateHigh,
  SagazDLQDepthHigh, SagazOutboxLagHigh, SagazExecutionLatencyHigh,
  SagazSagaFailureRateHigh
- Each rule has summary, description, and runbook_url annotations
- docs/monitoring/alerting.md guide exists
- Grafana dashboard JSON in sagaz/resources has alert panels
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[3]
ALERTMANAGER_RULES_PATH = REPO_ROOT / "docs" / "monitoring" / "alertmanager-rules.yml"
ALERTING_GUIDE_PATH = REPO_ROOT / "docs" / "monitoring" / "alerting.md"
GRAFANA_DASHBOARD_PATH = (
    REPO_ROOT
    / "sagaz"
    / "resources"
    / "local"
    / "redis"
    / "monitoring"
    / "grafana"
    / "dashboards"
    / "grafana-dashboard-outbox.json"
)

REQUIRED_ALERT_NAMES = {
    "SagazCompensationRateHigh",
    "SagazDLQDepthHigh",
    "SagazOutboxLagHigh",
    "SagazExecutionLatencyHigh",
    "SagazSagaFailureRateHigh",
}


# ---------------------------------------------------------------------------
# YAML structure tests
# ---------------------------------------------------------------------------


class TestAlertManagerRulesFile:
    """The alertmanager-rules.yml file must exist, parse, and contain all rules."""

    def test_file_exists(self):
        assert ALERTMANAGER_RULES_PATH.exists(), f"{ALERTMANAGER_RULES_PATH} does not exist"

    def test_file_is_valid_yaml(self):
        content = ALERTMANAGER_RULES_PATH.read_text()
        parsed = yaml.safe_load(content)
        assert parsed is not None, "YAML file is empty or invalid"

    def test_top_level_has_groups_key(self):
        parsed = yaml.safe_load(ALERTMANAGER_RULES_PATH.read_text())
        assert "groups" in parsed, "Top-level 'groups' key is missing"

    def test_groups_is_a_list(self):
        parsed = yaml.safe_load(ALERTMANAGER_RULES_PATH.read_text())
        assert isinstance(parsed["groups"], list)
        assert len(parsed["groups"]) >= 1

    def _collect_alert_rules(self) -> list[dict]:
        parsed = yaml.safe_load(ALERTMANAGER_RULES_PATH.read_text())
        rules: list[dict] = []
        for group in parsed.get("groups", []):
            for rule in group.get("rules", []):
                if "alert" in rule:
                    rules.append(rule)
        return rules

    def test_all_required_alert_names_present(self):
        rules = self._collect_alert_rules()
        names = {r["alert"] for r in rules}
        missing = REQUIRED_ALERT_NAMES - names
        assert not missing, f"Missing alert rules: {missing}"

    @pytest.mark.parametrize("alert_name", sorted(REQUIRED_ALERT_NAMES))
    def test_each_rule_has_summary_annotation(self, alert_name):
        rules = self._collect_alert_rules()
        rule = next((r for r in rules if r["alert"] == alert_name), None)
        assert rule is not None, f"Alert '{alert_name}' not found"
        annotations = rule.get("annotations", {})
        assert "summary" in annotations, f"Alert '{alert_name}' missing 'summary' annotation"

    @pytest.mark.parametrize("alert_name", sorted(REQUIRED_ALERT_NAMES))
    def test_each_rule_has_description_annotation(self, alert_name):
        rules = self._collect_alert_rules()
        rule = next((r for r in rules if r["alert"] == alert_name), None)
        assert rule is not None
        annotations = rule.get("annotations", {})
        assert "description" in annotations, (
            f"Alert '{alert_name}' missing 'description' annotation"
        )

    @pytest.mark.parametrize("alert_name", sorted(REQUIRED_ALERT_NAMES))
    def test_each_rule_has_runbook_url_annotation(self, alert_name):
        rules = self._collect_alert_rules()
        rule = next((r for r in rules if r["alert"] == alert_name), None)
        assert rule is not None
        annotations = rule.get("annotations", {})
        assert "runbook_url" in annotations, (
            f"Alert '{alert_name}' missing 'runbook_url' annotation"
        )

    @pytest.mark.parametrize("alert_name", sorted(REQUIRED_ALERT_NAMES))
    def test_each_rule_has_severity_label(self, alert_name):
        rules = self._collect_alert_rules()
        rule = next((r for r in rules if r["alert"] == alert_name), None)
        assert rule is not None
        labels = rule.get("labels", {})
        assert "severity" in labels, f"Alert '{alert_name}' missing 'severity' label"

    @pytest.mark.parametrize("alert_name", sorted(REQUIRED_ALERT_NAMES))
    def test_each_rule_has_expr(self, alert_name):
        rules = self._collect_alert_rules()
        rule = next((r for r in rules if r["alert"] == alert_name), None)
        assert rule is not None
        assert "expr" in rule, f"Alert '{alert_name}' missing 'expr' field"
        assert rule["expr"], f"Alert '{alert_name}' has empty 'expr'"

    @pytest.mark.parametrize("alert_name", sorted(REQUIRED_ALERT_NAMES))
    def test_each_rule_has_for_field(self, alert_name):
        rules = self._collect_alert_rules()
        rule = next((r for r in rules if r["alert"] == alert_name), None)
        assert rule is not None
        assert "for" in rule, f"Alert '{alert_name}' missing 'for' field"


# ---------------------------------------------------------------------------
# Alerting guide
# ---------------------------------------------------------------------------


class TestAlertingGuide:
    """docs/monitoring/alerting.md must exist and contain loading instructions."""

    def test_file_exists(self):
        assert ALERTING_GUIDE_PATH.exists(), f"{ALERTING_GUIDE_PATH} does not exist"

    def test_file_is_markdown(self):
        content = ALERTING_GUIDE_PATH.read_text()
        assert content.strip().startswith("#"), "alerting.md should start with a heading"

    def test_file_mentions_alertmanager_rules(self):
        content = ALERTING_GUIDE_PATH.read_text().lower()
        assert "alertmanager-rules.yml" in content or "alertmanager" in content
