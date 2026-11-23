"""Write validated data back out as YAML.

Only what the schema holds is written, so comments, anchors, tags and
directives in a file that was read do not survive being written again.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Final

import yaml
from pydantic import AnyUrl, BaseModel

__all__ = ["dump_yaml"]

_LINE_WIDTH: Final = 80


class _Dumper(yaml.SafeDumper):
    """Safe YAML dumper for the value types the models use; never emits aliases."""

    def ignore_aliases(self, data: object) -> bool:  # noqa: ARG002
        """Write a repeated value out in full each time."""
        return True


def _represent_decimal(dumper: _Dumper, value: Decimal) -> yaml.ScalarNode:
    kind = "int" if value == value.to_integral_value() else "float"
    return dumper.represent_scalar(f"tag:yaml.org,2002:{kind}", f"{value.normalize():f}")


def _represent_as_text(dumper: _Dumper, value: object) -> yaml.ScalarNode:
    return dumper.represent_str(str(value))


_Dumper.add_representer(Decimal, _represent_decimal)
_Dumper.add_multi_representer(AnyUrl, _represent_as_text)
_Dumper.add_multi_representer(StrEnum, _represent_as_text)


def dump_yaml(model: BaseModel) -> str:
    """Return a model as YAML that loads back to an equal model.

    Every top-level field is written; below that, fields left at their
    defaults are omitted. The output depends only on the model's values, so
    writing a loaded file twice gives the same text.
    """
    trimmed = model.model_dump(exclude_defaults=True)
    fields = {name: trimmed.get(name, value) for name, value in model.model_dump().items()}
    return yaml.dump(
        fields,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        width=_LINE_WIDTH,
    )
