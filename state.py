from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class BotState:
    step: str = "IDLE"
    data: Dict[str, object] = field(default_factory=dict)

    def reset(self) -> None:
        self.step = "IDLE"
        self.data.clear()


def normalize_bank(bank: str) -> str:
    # evita "Itau" vs "Itaú" nas callbacks
    m = {
        "BB": "BB",
        "Itau": "Itaú",
        "Itaú": "Itaú",
        "XP": "XP",
        "Infinite": "Infinite",
    }
    return m.get(bank, bank)


def parse_desc_and_value(text: str) -> Optional[tuple[str, str]]:
    # esperado: "mercado,-150,00" ou "mercado,-150.00" ou "mercado, -150,00"
    if "," not in text:
        return None
    nome, valor = text.split(",", 1)
    nome = nome.strip()
    valor = valor.strip()
    if not nome or not valor:
        return None
    return nome, valor
