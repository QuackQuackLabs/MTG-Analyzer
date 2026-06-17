"""Domain models for Scryfall cards and rulings.

Designed to be built directly from raw Scryfall JSON via ``Card.model_validate``.
Unknown fields are ignored, so the models stay lean while tolerating Scryfall's
large object. See the ``scryfall-api`` skill for field semantics and the
double-faced-card rules encoded in the helper methods below.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Layouts where mana_cost / oracle_text / images / P-T live on each card_faces
# entry rather than the top level. cmc / color_identity / legalities stay on top.
MULTIFACE_LAYOUTS = frozenset(
    {"transform", "modal_dfc", "meld", "split", "flip", "adventure", "reversible_card"}
)


class CardFace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    mana_cost: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    colors: list[str] = Field(default_factory=list)
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    image_uris: dict[str, str] | None = None


class Card(BaseModel):
    """A card keyed on its gameplay identity (``oracle_id``)."""

    model_config = ConfigDict(extra="ignore")

    # Identity
    oracle_id: str | None = None  # absent on some reversible cards (lives per-face)
    id: str  # Scryfall id of this specific printing
    name: str

    # Gameplay (always trustworthy at top level, even for DFCs)
    cmc: float = 0.0
    color_identity: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    legalities: dict[str, str] = Field(default_factory=dict)
    layout: str = "normal"
    produced_mana: list[str] = Field(default_factory=list)
    game_changer: bool = False
    reserved: bool = False
    edhrec_rank: int | None = None

    # May be absent at top level on multi-faced cards (read from faces instead)
    mana_cost: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    image_uris: dict[str, str] | None = None
    card_faces: list[CardFace] = Field(default_factory=list)

    # Printing-level
    set: str | None = None
    set_name: str | None = None
    collector_number: str | None = None
    rarity: str | None = None
    prices: dict[str, str | None] = Field(default_factory=dict)

    @property
    def is_multifaced(self) -> bool:
        return self.layout in MULTIFACE_LAYOUTS and bool(self.card_faces)

    def commander_legality(self) -> str:
        """``legal`` / ``not_legal`` / ``banned`` / ``restricted`` (default not_legal)."""
        return self.legalities.get("commander", "not_legal")

    def is_commander_legal(self) -> bool:
        return self.commander_legality() == "legal"

    def get_oracle_text(self) -> str:
        """Full rules text, joining faces for multi-faced cards."""
        if self.oracle_text is not None:
            return self.oracle_text
        return "\n//\n".join(f.oracle_text or "" for f in self.card_faces)

    def get_mana_cost(self) -> str:
        if self.mana_cost:
            return self.mana_cost
        return " // ".join(f.mana_cost or "" for f in self.card_faces)

    def get_image(self, size: str = "normal") -> str | None:
        """Image URL of the given size; falls back to the front face for DFCs."""
        if self.image_uris and size in self.image_uris:
            return self.image_uris[size]
        for face in self.card_faces:
            if face.image_uris and size in face.image_uris:
                return face.image_uris[size]
        return None

    def usd_price(self) -> float | None:
        raw = self.prices.get("usd")
        return float(raw) if raw else None


class Ruling(BaseModel):
    model_config = ConfigDict(extra="ignore")

    oracle_id: str
    source: str  # "wotc" or "scryfall"
    published_at: str
    comment: str
