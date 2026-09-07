# SPDX-License-Identifier: AGPL-3.0-or-later
"""A feature switched off is off. `H05`.

`DEFAULT_FEATURES` has eight flags. Before this row **seven of them did
nothing**: `load_features()` had three callers and every one was read-write
plumbing, so no server-side code branched on any flag. Enforcement was entirely
client-side — `static/app.js` set `display:none` on four elements — which meant
an admin who turned off Deep Research got a `200`, the toggle stayed off, and
the feature was still there for anyone who knew the URL. `web_fetch`, `memory`
and `rag` had no consumers at all, in any layer.

THREE LAYERS, BECAUSE A FEATURE IS THREE THINGS.

  1. **The agent.** `src/tool_security.feature_disabled_tools()` contributes
     into the denylist `execute_tool_block` already enforces. This is the half
     the row is really about: a flag the model does not honour is not a control,
     it is a label.
  2. **The HTTP surface.** `require_feature(...)` below, mounted as a router
     dependency so it covers every route in a router rather than every route
     author remembering.
  3. **The UI.** Still `static/app.js`, and still the least important of the
     three — hiding a button was never the problem, it was that hiding a button
     was ALL there was.

403 AND NOT 404.

`P16-12`'s metrics endpoint returns 404 when disabled, on the grounds that off
should look like never built. That is right for an attack surface nobody asked
for and wrong here: this is a feature a person can see in the product, that
their administrator switched off, and telling them it does not exist is a lie
they can disprove by asking a colleague. The status says refused; the message
says who refused it.

WHAT DOES NOT APPEAR HERE.

`sensitive_filter` is a display filter — it redacts what is shown and removes no
capability, so there is no route whose absence implements it. Mapping it to
something would be inventing a meaning the switch never had.
"""
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def feature_enabled(name: str, features: Optional[dict] = None) -> bool:
    """Is this feature on?

    Fails **open** on a read error. `load_features()` already falls back to the
    shipped defaults for every failure it can see, and a features file that will
    not parse must not silently take half the product away from someone —
    especially since the failure would look identical to an admin having turned
    everything off deliberately.

    An unknown name is on. This function answers "has somebody switched this
    off", and nobody can have switched off a flag that does not exist; treating
    unknown as off would turn a typo in a call site into a silently dead
    feature, which is the exact defect this row is fixing.
    """
    if features is None:
        try:
            from src.settings import load_features
            features = load_features()
        except Exception as exc:
            logger.warning("Unable to read feature flags (%s); treating %r as on",
                           exc, name)
            return True
    if not isinstance(features, dict) or name not in features:
        return True
    return bool(features.get(name))


def require_feature(name: str, *, label: Optional[str] = None) -> Callable[..., Any]:
    """A FastAPI dependency that refuses when `name` is switched off.

    Mounted on the ROUTER rather than on each route:

        router = APIRouter(dependencies=[Depends(require_feature("gallery"))])

    which is the difference between a gate and a convention. Per-route
    decoration means every future route in the file has to remember, and the one
    that forgets is indistinguishable from the state this row found.
    """
    pretty = label or name.replace("_", " ")

    def _guard() -> None:
        if feature_enabled(name):
            return
        from fastapi import HTTPException
        raise HTTPException(
            403,
            f"{pretty} is switched off for this install. "
            f"An administrator can turn it back on in Settings.",
        )

    _guard.__name__ = f"require_feature_{name}"
    _guard.__doc__ = f"Refuses every request in this router when `{name}` is off (H05)."
    return _guard
