from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Contact:
    name: str
    address: str
    note: str = ""

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Contact | None":
        name = str(raw.get("name", "")).strip()
        address = str(raw.get("address", "")).strip()
        note = str(raw.get("note", "")).strip()
        if not name or not address:
            return None
        return Contact(name=name, address=address, note=note)

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "address": self.address, "note": self.note}


def load_contacts(config: dict[str, Any]) -> list[Contact]:
    contacts_raw = config.get("contacts", [])
    if not isinstance(contacts_raw, list):
        return []
    contacts: list[Contact] = []
    for entry in contacts_raw:
        if isinstance(entry, dict):
            contact = Contact.from_dict(entry)
            if contact:
                contacts.append(contact)
    return contacts


def save_contacts_to_config(config: dict[str, Any], contacts: list[Contact]) -> None:
    config["contacts"] = [c.to_dict() for c in contacts]
