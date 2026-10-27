# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B713` — the memory corpus can say "nothing should come back", and the
harness prints what each engine does then.

`retrieval_eval._load` refused a memory probe whose `expect` was empty, so
every probe in `retrieval_probe.json` asserted a presence and none an absence,
and no retrieval change could be held to a false-positive number. `P13-16`
measured exactly that number outside the harness — widening stage one took
off-topic injection from 0.12 to 1.50 memories per query over eight questions
in a scratch script — and a number produced that way cannot be re-run.

The shape is unmistakable on the page (`Law 10`): `"absent": true` with a
`why`, never `"expect": []`, which a reader cannot tell from a forgotten field.
`score` reports `refusal` (absent probes that returned nothing) and `noise`
(memories returned per absent probe) beside recall@k, from the probes it can,
and the fixture carries eight such questions — the two `P13-16` quoted among
them.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_EVAL = _REPO / ".pantheon" / "retrieval_eval.py"
_FIXTURE = _REPO / ".pantheon" / "fixtures" / "retrieval_probe.json"
sys.path.insert(0, str(_REPO / ".pantheon"))
import retrieval_eval  # noqa: E402

_MEMORIES = [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}]


def _write(tmp_path, probes):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"provenance": "fixture", "memories": _MEMORIES,
                                "probes": probes}), encoding="utf-8")
    return path


@pytest.mark.parametrize("probe,says", [
    ({"query": "q", "expect": []}, "absent"),
    ({"query": "q", "absent": "yes", "why": "w"}, "`true` or it is left out"),
    ({"query": "q", "absent": False, "expect": ["a"]}, "`true` or it is left out"),
    ({"query": "q", "absent": True, "expect": ["a"], "why": "w"}, "cannot be both"),
    ({"query": "q", "absent": True}, "does not say why"),
])
def test_an_absence_that_could_be_misread_is_refused(tmp_path, probe, says):
    path = _write(tmp_path, [{"query": "real", "expect": ["a"]}, probe])
    with pytest.raises(SystemExit) as e:
        retrieval_eval._load(path)
    assert says in str(e.value)


def test_a_corpus_of_only_absences_has_nothing_to_recall(tmp_path):
    path = _write(tmp_path, [{"query": "q", "absent": True, "why": "w"}])
    with pytest.raises(SystemExit, match="nothing to recall"):
        retrieval_eval._load(path)


def test_absence_is_scored_apart_and_moves_no_recall_number(tmp_path):
    present = [{"query": "q1", "expect": ["a"]}, {"query": "q2", "expect": ["b"]}]
    absent = [{"query": "weather", "absent": True, "why": "w"},
              {"query": "football", "absent": True, "why": "w"}]
    ranked = {"q1": ["a"], "q2": ["a", "b"], "weather": [], "football": ["a", "b", "a"]}
    without = retrieval_eval.score(retrieval_eval._load(_write(tmp_path, present)), ranked, 2)
    corpus = retrieval_eval._load(_write(tmp_path, present + absent))
    out = retrieval_eval.score(corpus, ranked, 2)
    for key in ("n", "recall@2", "mrr", "returned", "precision", "hits"):
        assert out[key] == without[key], key
    assert out["absent_n"] == 2 and out["quiet"] == 1
    assert out["refusal"] == 0.5
    assert out["noise"] == 1.0                      # (0 + 2 within k) / 2
    assert [s["query"] for s in out["spills"]] == ["football"]
    assert without["refusal"] is None, "no absent question is not a perfect refusal"


def test_the_fixture_asks_what_should_find_nothing():
    probes = json.loads(_FIXTURE.read_text(encoding="utf-8"))["probes"]
    absent = [p["query"] for p in probes if p.get("absent")]
    assert len(absent) >= 8
    # The two `P13-16` quoted, so its measurement has a home.
    assert "convert 40 fahrenheit to celsius" in absent
    assert "who won the 1998 world cup" in absent
    retrieval_eval._load(_FIXTURE)                  # and the file loads


def test_the_shipped_command_prints_a_refusal_column():
    proc = subprocess.run([sys.executable, str(_EVAL), "--engine", "manager"],
                          capture_output=True, text=True, cwd=str(_REPO), timeout=180)
    assert proc.returncode == 0, proc.stderr
    row = next(line for line in proc.stdout.splitlines() if line.strip().startswith("manager"))
    assert "refusal 1.00" in row and "noise 0.00/query (8/8)" in row, row
    assert "+ 8 that should find nothing" in proc.stdout


def test_the_product_path_off_topic_number_is_reproducible():
    """`P13-16`'s number, on the product's own path (`--engine local`, the
    in-process index) and from the shipped command. Skipped, with the reason,
    where the embedding model is not on this machine."""
    corpus = retrieval_eval._load(_FIXTURE)
    try:
        first = retrieval_eval.score(corpus, retrieval_eval.ENGINES["local"](corpus, 5), 5)
    except retrieval_eval.SkipEngine as e:
        pytest.skip(f"no in-process embedding lane here: {e}")
    again = retrieval_eval.score(corpus, retrieval_eval.ENGINES["local"](corpus, 5), 5)
    assert first["noise"] == again["noise"]
    spilled = {s["query"]: s["got"] for s in first["spills"]}
    # The collision `P13-16` named: the loft conversion, on the word `convert`.
    assert spilled.get("convert 40 fahrenheit to celsius") == ["m10"], spilled
    assert first["noise"] < 1.5, "as wide as the widened stage one P13-16 refused"
