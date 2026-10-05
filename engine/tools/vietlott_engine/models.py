from dataclasses import dataclass


GAME_LIMITS = {"mega645": 45, "power655": 55}


@dataclass(frozen=True)
class PrizeTier:
    name: str
    winner_count: int
    prize_value_vnd: int
    match_pattern: str = ""


@dataclass(frozen=True)
class Draw:
    game: str
    draw_id: str
    draw_date: str
    numbers: tuple[int, ...]
    source_url: str
    content_hash: str
    special_number: int | None = None
    detail_url: str = ""
    prize_tiers: tuple[PrizeTier, ...] = ()
    detail_retrieved_at: str = ""
