"""pricing.json is shared with the viewer: keep its shape valid."""

from __future__ import annotations

import json
from importlib import resources


def test_pricing_table_shape() -> None:
    table = json.loads(resources.files("agent_xray").joinpath("pricing.json").read_text("utf-8"))
    assert table["per_tokens"] == 1_000_000
    models = table["models"]
    assert models, "no models"
    for name, price in models.items():
        assert name == name.lower(), (
            f"{name}: keys must be lowercase (the viewer matches lowercase)"
        )
        assert set(price) == {"input", "output"}, name
        assert all(isinstance(v, int | float) and v >= 0 for v in price.values()), name
    assert models["scripted-fake"] == {"input": 0, "output": 0}  # the example's fake model is free
