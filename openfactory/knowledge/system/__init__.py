"""The system layer (ADR-0052 D17, #268 slice 2): the product's topology across its sources.

`derive` reads what the repositories declare and returns a `SystemMap`; `render`/`write_system`
turn it into the files published at `.okf/system/` in the context repository; `refresh` does both
for a registered product and publishes under the product's semaphore. No model, no network in the
derivation, and nothing from a repository is ever run.
"""

from __future__ import annotations

from openfactory.knowledge.system.contracts import SystemMap
from openfactory.knowledge.system.derive import derive
from openfactory.knowledge.system.render import (
    SYSTEM_DIRNAME,
    derived_key,
    render,
    write_system,
)
from openfactory.knowledge.system.tree import SourceTree

__all__ = ["SYSTEM_DIRNAME", "SourceTree", "SystemMap", "derive", "derived_key", "render",
           "write_system"]
