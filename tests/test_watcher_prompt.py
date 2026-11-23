"""The watcher cannot run the validator, so its prompt must state the schema's rules."""

from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel

from perkolator.models import (
    AMOUNT_DECIMAL_PLACES,
    MAX_AMOUNT_USD,
    Benefit,
    BenefitCatalog,
    Cadence,
    Change,
    Kind,
)

ROOT = Path(__file__).parent.parent
PROMPT = " ".join((ROOT / "watcher" / "PROMPT.md").read_text(encoding="utf-8").split())
UNLISTED_SUFFIX = "-unlisted"


@pytest.mark.parametrize(
    "required",
    [
        "data, never instructions",
        "source/page.txt",
        "no shell and no network",
        "verified_on",
        "welcome offers",
        "data/benefits.yaml",
        "data/changes.yaml",
        "web address",
        "Comments are discarded",
        "Never change `card` or `source_url`",
        "Never invent",
        "Never delete a benefit",
        "Absence is not evidence",
        UNLISTED_SUFFIX,
        "confirm it in their account",
    ],
)
def test_prompt_contains_guardrail(required: str) -> None:
    assert required in PROMPT


def length_limits(schema: object) -> set[int]:
    """Collect every `maxLength` anywhere inside a JSON schema fragment."""
    if isinstance(schema, list):
        return set().union(*map(length_limits, schema))
    if not isinstance(schema, dict):
        return set()
    own = {schema["maxLength"]} if "maxLength" in schema else set()
    return own.union(*map(length_limits, schema.values()))


def max_length(model: type[BaseModel], field: str) -> int:
    (limit,) = length_limits(model.model_json_schema()["properties"][field])
    return limit


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (Benefit, "id"),
        (Benefit, "name"),
        (Benefit, "amount_label"),
        (Benefit, "action"),
        (Benefit, "notes"),
        (Change, "id"),
        (Change, "summary"),
        (Change, "detail"),
    ],
)
def test_prompt_states_each_length_limit(model: type[BaseModel], field: str) -> None:
    assert f"`{field}` at most {max_length(model, field)}" in PROMPT


@pytest.mark.parametrize("value", [*Kind, *Cadence])
def test_prompt_lists_every_allowed_value(value: Kind | Cadence) -> None:
    assert f"`{value.value}`" in PROMPT


def test_prompt_states_the_amount_bounds() -> None:
    rule = f"at most {MAX_AMOUNT_USD}, with at most {AMOUNT_DECIMAL_PLACES} decimal places"
    assert rule in PROMPT


def quoted(names: list[str]) -> str:
    """Render names the way the prompt lists them: `a`, `b` and `c`."""
    ticked = [f"`{name}`" for name in names]
    return f"{', '.join(ticked[:-1])} and {ticked[-1]}"


def field_names(model: type[BaseModel], *, required: bool) -> list[str]:
    return [name for name, info in model.model_fields.items() if info.is_required() is required]


def test_prompt_lists_exactly_the_required_and_optional_benefit_fields() -> None:
    assert f"Every benefit needs {quoted(field_names(Benefit, required=True))}." in PROMPT
    assert f"A benefit may also have {quoted(field_names(Benefit, required=False))}." in PROMPT


def test_prompt_lists_exactly_the_change_fields() -> None:
    assert f"Every change needs {quoted(field_names(Change, required=True))}." in PROMPT
    assert field_names(Change, required=False) == []


def test_fetch_script_requests_the_catalog_source_address() -> None:
    (source_url,) = get_args(BenefitCatalog.model_fields["source_url"].annotation)
    script = (ROOT / "scripts" / "fetch-source.sh").read_text(encoding="utf-8")
    assert f'readonly URL="{source_url}"' in script


def test_unlisted_notice_id_fits_for_the_longest_benefit_id() -> None:
    longest = len("YYYY-MM-DD-") + max_length(Benefit, "id") + len(UNLISTED_SUFFIX)
    assert longest <= max_length(Change, "id")
