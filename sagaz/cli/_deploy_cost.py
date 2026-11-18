"""Monthly cost estimate for ``sagaz deploy --cost-estimate`` (offline).

Each Terraform module ships a ``cost.json`` with monthly on-demand list prices
keyed by the module's sizing variables. The estimate combines it with the
variables' defaults (read from ``variables.tf``) and the user's overrides.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# ``variable "name" {`` ... ``default = <scalar>`` (maps and lists are skipped).
_VARIABLE = re.compile(r'variable\s+"(?P<name>[^"]+)"\s*\{(?P<body>.*?)\n\}', re.S)
_DEFAULT = re.compile(r"^\s*default\s*=\s*(?P<value>.+?)\s*$", re.M)
_MEMORY = re.compile(r"^(?P<number>[\d.]+)\s*(?P<unit>Mi|Gi|M|G)?$")
_HA_VALUES = {"true", "regional", "standard_ha", "yes", "1"}


@dataclass(frozen=True)
class CostLine:
    label: str
    monthly: float | None  # None: the configured value has no list price in cost.json


@dataclass(frozen=True)
class CostEstimate:
    provider: str
    currency: str
    region: str
    priced_at: str
    lines: list[CostLine]
    notes: list[str]

    @property
    def total(self) -> float:
        return round(sum(line.monthly or 0.0 for line in self.lines), 2)

    @property
    def complete(self) -> bool:
        return all(line.monthly is not None for line in self.lines)


def _scalar(text: str) -> Any:
    text = text.split("#", 1)[0].split("//", 1)[0].strip()
    if text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def tf_defaults(variables_tf: str) -> dict[str, Any]:
    """Scalar ``default`` values of the variables declared in ``variables.tf``."""
    defaults = {}
    for match in _VARIABLE.finditer(variables_tf):
        if default := _DEFAULT.search(match.group("body")):
            value = _scalar(default.group("value"))
            if value is not None:
                defaults[match.group("name")] = value
    return defaults


def _number(value: Any, unit: str | None = None) -> float:
    """A numeric value; memory strings ("512Mi", "1Gi") convert to GiB when unit is GiB."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    match = _MEMORY.match(str(value).strip())
    if not match:
        msg = f"not a number: {value!r}"
        raise ValueError(msg)
    number = float(match.group("number"))
    if unit == "GiB" and match.group("unit") in ("Mi", "M"):
        return number / 1024
    return number


def _is_ha(value: Any) -> bool:
    return str(value).strip().lower() in _HA_VALUES


def _multiplier(item: dict[str, Any], value: Any) -> float:
    """Factor for HA settings: a ``multipliers`` map by value, or ``multiplier`` when truthy."""
    if "multipliers" in item:
        return float(item["multipliers"].get(str(value), 1))
    return float(item.get("multiplier", 2)) if _is_ha(value) else 1.0


def _line(item: dict[str, Any], values: dict[str, Any]) -> CostLine:
    prices = item["prices"]
    variable = item.get("variable")
    key = str(values.get(variable)) if variable else "*"
    price = prices.get(key, prices.get("*"))
    label = f"{item['label']} ({values.get(variable)})" if variable else item["label"]
    if price is None:
        return CostLine(label, None)
    monthly = float(price)
    if quantity := item.get("quantity_variable"):
        monthly *= _number(values.get(quantity, 1))
    if per_unit := item.get("per_unit_variable"):
        monthly *= _number(values.get(per_unit, 0), item.get("per_unit_unit")) / float(
            item.get("per_unit_divisor", 1)
        )
    if multiplier := item.get("multiplier_variable"):
        monthly *= _multiplier(item, values.get(multiplier))
    return CostLine(label, round(monthly, 2))


def estimate(cost: dict[str, Any], values: dict[str, Any]) -> CostEstimate:
    """Monthly cost of a module configured with ``values`` (defaults plus overrides)."""
    lines = [_line(item, values) for item in cost.get("items", [])]
    lines += [CostLine(fixed["label"], float(fixed["monthly"])) for fixed in cost.get("fixed", [])]
    return CostEstimate(
        provider=cost.get("provider", "?"),
        currency=cost.get("currency", "USD"),
        region=cost.get("region", "?"),
        priced_at=cost.get("priced_at", "?"),
        lines=lines,
        notes=list(cost.get("notes", [])),
    )


def render(result: CostEstimate) -> str:
    """Plain-text table of an estimate."""
    width = max([len(line.label) for line in result.lines] + [5])
    rows = [f"Estimated monthly cost ({result.provider}, {result.region}, {result.currency})"]
    for line in result.lines:
        amount = "not priced" if line.monthly is None else f"{line.monthly:>10,.2f}"
        rows.append(f"  {line.label:<{width}}  {amount}")
    rows.append(f"  {'Total':<{width}}  {result.total:>10,.2f}")
    rows.append(f"List prices as of {result.priced_at}; approximate.")
    rows += [f"  - {note}" for note in result.notes]
    if not result.complete:
        rows.append("Some configured sizes have no list price; the total excludes them.")
    return "\n".join(rows)
