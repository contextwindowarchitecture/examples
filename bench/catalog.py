"""OpenRouter's public model list, read for what a run needs: which models exist, what they cost, and whether they take
tools, which 04 and 05 send; and for what explains a model's numbers afterwards: its own tokenizer, its context limit
and the temperature it samples at when a request sets none. Reading it needs no key."""
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
    tokenizer: str | None = None       # the family of the model's own tokenizer, as OpenRouter names it
    context: int | None = None         # its context limit, in its own tokens
    temperature: float | None = None   # what it samples at by default: the examples send no sampling settings

    @property
    def free(self) -> bool:
        return self.input_price == 0 and self.output_price == 0


def parse(data: dict[str, Any]) -> dict[str, Listing]:
    return {model["id"]: Listing(input_price=float(model["pricing"]["prompt"]),
                                 output_price=float(model["pricing"]["completion"]),
                                 tools="tools" in model.get("supported_parameters", []),
                                 tokenizer=(model.get("architecture") or {}).get("tokenizer"),
                                 context=model.get("context_length"),
                                 temperature=(model.get("default_parameters") or {}).get("temperature"))
            for model in data["data"]}


def fetch(url: str = URL) -> dict[str, Listing]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return parse(json.load(response))
