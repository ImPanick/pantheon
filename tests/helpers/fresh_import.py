# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop a module so the next import binds to whatever stubs are installed —
and put `sys.modules` back exactly as it was.

`monkeypatch.delitem(sys.modules, name, raising=False)` does **not** do the
second half. pytest's implementation records an undo entry only when the key was
actually there:

    if name not in dic:
        if raising:
            raise KeyError(name)
    else:
        self._setitem.append((dic, name, dic.get(name, notset)))
        del dic[name]

So on the common path — a module this file is the first to import — nothing is
recorded, the fresh import under the test's stubs lands in `sys.modules`, and it
is still there for every later file in the session. That is how
`routes.api_token_routes.ApiToken` came to be a `MagicMock` for the back half of
an 11,100-test run: the module in `sys.modules` was the real one by `__file__`
and a stub by contents, which is the exact shape `B202` and `B271` describe
(`B525`).

`monkeypatch.setitem` records either way — the previous value, or `notset` for
"was absent", which its undo turns into a delete. So setting a placeholder and
then removing the key ourselves gets the restore right in both cases.
"""
import sys

_PLACEHOLDER = object()


def drop_for_fresh_import(monkeypatch, *names):
    """Remove `names` from `sys.modules`, restoring them at teardown.

    Imported or not before the call, `sys.modules` is the same afterwards.
    Returns nothing: the point is the re-import the caller then does itself, so
    that the stubs it wants are the ones in place when the module body runs.
    """
    for name in names:
        monkeypatch.setitem(sys.modules, name, _PLACEHOLDER)
        sys.modules.pop(name, None)
