from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandInput:
    type: str = "text"
    label: str = ""
    placeholder: str = ""
    required: bool = False
    max_length: int = 256

    def to_json(self) -> dict:
        return {"type": self.type, "label": self.label, "placeholder": self.placeholder,
                "required": self.required, "maxLength": self.max_length}


@dataclass
class Command:
    """A bot command shown to users."""

    name: str
    value: str
    description: str = ""
    input: Optional[CommandInput] = None

    def to_json(self) -> dict:
        data = {"name": self.name, "value": self.value, "description": self.description}
        if self.input is not None:
            data["input"] = self.input.to_json()
        return data
