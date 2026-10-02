"""OpenRouter's public model list, read for what a run needs: which models exist, what they cost, and whether they take
tools, which 04 and 05 send. Reading it needs no key."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class Listing:
    input_price: float   # dollars per input token
    output_price: float  # dollars per output token, reasoning included
    tools: bool

    @property
    def free(self) -> bool:
        return self.input_price == 0 and self.output_price == 0


def parse(data: dict[str, Any]) -> dict[str, Listing]:
    return {model["id"]: Listing(input_price=float(model["pricing"]["prompt"]),
                                 output_price=float(model["pricing"]["completion"]),
                                 tools="tools" in model.get("supported_parameters", []))
            for model in data["data"]}


def fetch(url: str = URL) -> dict[str, Listing]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return parse(json.load(response))
