"""Building typed appliances for tests, and reading what they sent."""

from __future__ import annotations

import json
from typing import Any


def code(data_hex: str) -> dict[str, Any]:
    """A NEC code, as a board decodes it and the integration stores it."""
    return {"Protocol": "NEC", "Bits": 32, "Data": data_hex}


def typed(
    kind: str, title: str, key: str, roles: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    """A typed appliance subentry as the flow writes it, on emitter 3."""
    return {
        "data": {"channel": 3, "roles": roles, **extra},
        "subentry_type": kind,
        "title": title,
        "unique_id": key,
    }


def sent(mqtt_mock) -> list[str]:
    """The Data of every IRSend published so far, in order."""
    return [
        json.loads(call.args[1])["Data"]
        for call in mqtt_mock.async_publish.call_args_list
        if call.args[0].endswith("/IRSend")
    ]
