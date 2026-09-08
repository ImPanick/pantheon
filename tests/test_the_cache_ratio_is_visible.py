# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-22` — the two numbers that decide what a run costs, and where they went.

`cache_read_input_tokens` and `cache_creation_input_tokens` were pulled out of
the provider's stream, written to a `logger.info`, and dropped. Nothing else
ever saw them.

The row's own words for why that matters: cache hit ratio is *"the single
biggest lever on real cost"*. A cached input token costs roughly a tenth of a
fresh one, so a run whose stable prefix stops being cacheable — a timestamp
folded into the system message, a tool list that changes per turn — gets an
order of magnitude more expensive **with no visible change at all**. There is
nothing in the product that would have told anyone.

The rule everywhere here is that **absence means "not reported"**. A local
llama.cpp has no prompt cache; a zero or a "Cache 0% hit" row there would be a
claim about a mechanism that does not exist rather than a measurement of one
that does.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.agent_loop as agent_loop
from src.agent_loop import _usage_bucket, _usage_bucket_summary
from src.llm_core import _normalize_usage_counts

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "chatRenderer.js"


# ── off the wire ──────────────────────────────────────────────────────────────


def test_the_counts_survive_normalisation():
    usage = _normalize_usage_counts(100, 50, 900, 400)
    assert usage["cache_read_input_tokens"] == 900
    assert usage["cache_creation_input_tokens"] == 400


def test_a_provider_that_reports_no_cache_says_nothing():
    usage = _normalize_usage_counts(100, 50)
    assert "cache_read_input_tokens" not in usage
    assert "cache_creation_input_tokens" not in usage


@pytest.mark.parametrize("read, write", [(-1, 0), ("x", 0), (0, None), (1.5, 0), (True, 0)])
def test_a_count_that_is_not_a_count_is_dropped_not_guessed(read, write):
    usage = _normalize_usage_counts(100, 50, read, write)
    assert usage is not None, "a bad cache count must not lose the token counts too"
    assert usage["input_tokens"] == 100
    assert "cache_read_input_tokens" not in usage or usage["cache_read_input_tokens"] > 0


def test_the_stream_keeps_what_it_used_to_only_log():
    core = (_REPO / "src" / "llm_core.py").read_text(encoding="utf-8")
    assert "_anth_cache_read = _u.get(\"cache_read_input_tokens\", 0)" in core
    assert "_anth_cache_read,\n                                _anth_cache_write," in core
    assert '"[anthropic-cache] read=%s write=%s fresh_input=%s"' in core, (
        "the log line is worth keeping; it is the only record when a stream dies"
    )


# ── per round, then per turn ──────────────────────────────────────────────────


def _bucket(**kwargs):
    return _usage_bucket(
        round_num=kwargs.pop("round_num", 1), model="m", endpoint_id=None,
        endpoint_label=None, endpoint_cost_tracked=None,
        input_tokens=kwargs.pop("input_tokens", 100),
        output_tokens=kwargs.pop("output_tokens", 50),
        usage_source="real", **kwargs,
    )


def test_a_round_carries_its_own_cache_numbers():
    # Per round, because a prefix that stops being cacheable stops at *a round*
    # — a per-turn total says the ratio dropped and not where.
    bucket = _bucket(cache_read=900, cache_write=100)
    assert bucket["cache_read_input_tokens"] == 900
    assert bucket["cache_creation_input_tokens"] == 100


def test_a_round_with_no_cache_carries_no_zeroes():
    assert "cache_read_input_tokens" not in _bucket()


def test_the_turn_sums_the_rounds():
    summary = _usage_bucket_summary([
        _bucket(round_num=1, cache_read=900, cache_write=100),
        _bucket(round_num=2, cache_read=800, cache_write=0),
    ])
    assert summary["cache_read_tokens"] == 1700
    assert summary["cache_write_tokens"] == 100


def test_the_ratio_counts_everything_that_went_in():
    # A hit rate measured against fresh tokens alone flatters itself: the
    # denominator is what was billed, which includes what was read from the
    # cache and what was written to it.
    summary = _usage_bucket_summary([_bucket(input_tokens=100, cache_read=900)])
    assert summary["cache_hit_ratio"] == 0.9


def test_a_turn_that_only_wrote_the_cache_scores_zero_and_says_so():
    # The first turn of a conversation: nothing to read yet, everything written.
    # `0.0` here is a real measurement, not an absence.
    summary = _usage_bucket_summary([_bucket(input_tokens=100, cache_write=900)])
    assert summary["cache_hit_ratio"] == 0.0
    assert summary["cache_write_tokens"] == 900


def test_a_turn_with_no_cache_reports_no_ratio():
    summary = _usage_bucket_summary([_bucket()])
    for key in ("cache_read_tokens", "cache_write_tokens", "cache_hit_ratio"):
        assert key not in summary, key


def test_the_ordinary_token_fields_are_untouched():
    summary = _usage_bucket_summary([_bucket(cache_read=900)])
    assert summary["input_tokens"] == 100
    assert summary["output_tokens"] == 50
    assert summary["total_tokens"] == 150
    assert summary["usage_source"] == "real"


def test_the_loop_reads_the_counts_off_the_usage_event():
    loop = (_REPO / "src" / "agent_loop.py").read_text(encoding="utf-8")
    assert 'u.get("cache_read_input_tokens", 0)' in loop
    assert "_round_cache_read += normalized_usage.get" in loop
    assert "cache_read=_round_cache_read," in loop


# ── on screen ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    """Execute the real row builder, lifted out by source."""
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    src = _MODULE.read_text(encoding="utf-8")
    start = src.index("export function promptCacheRows(")
    end = src.index("\nexport function displayMetrics(", start)
    body = src[start:end].replace("export function", "function", 1)
    d = tmp_path_factory.mktemp("cacherows")
    (d / "case.mjs").write_text(body + """
console.log(JSON.stringify(promptCacheRows(JSON.parse(process.argv[2]))));
""", encoding="utf-8")
    return d


def _row(rows: Path, metrics):
    proc = subprocess.run(["node", "case.mjs", json.dumps(metrics)], cwd=rows,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_ratio_is_on_screen(rows):
    html = _row(rows, {"cache_read_tokens": 1700, "cache_write_tokens": 100,
                       "cache_hit_ratio": 0.9231})
    assert "92.3% hit" in html
    assert "1,700 read" in html
    assert "100 written" in html


def test_a_provider_with_no_cache_gets_no_row(rows):
    # A row reading "Cache 0% hit" on a local llama.cpp is a claim about a
    # mechanism that does not exist.
    for metrics in ({}, {"cache_read_tokens": 0, "cache_write_tokens": 0},
                    {"input_tokens": 100, "output_tokens": 50}):
        assert _row(rows, metrics) == ""


def test_a_first_turn_that_only_wrote_the_cache_still_shows(rows):
    # Nothing was read and that is worth knowing — it is the turn that paid to
    # fill the cache the next one will read.
    html = _row(rows, {"cache_read_tokens": 0, "cache_write_tokens": 900,
                       "cache_hit_ratio": 0.0})
    assert "0% hit" in html and "900 written" in html


def test_a_ratio_nobody_computed_says_so_rather_than_zero(rows):
    html = _row(rows, {"cache_read_tokens": 900, "cache_write_tokens": 0})
    assert "n/a" in html


@pytest.mark.parametrize("bad", ["lots", None, "NaN", [], {}])
def test_junk_counts_draw_nothing(rows, bad):
    # A real NaN is not expressible in JSON — `json.dumps(float("nan"))` emits a
    # bare `NaN` that `JSON.parse` rejects, so the harness crashed rather than
    # the code. `"NaN"` is a legitimate JSON value that `Number()` turns into
    # one, which is the path a wire value would actually take.
    assert _row(rows, {"cache_read_tokens": bad, "cache_write_tokens": 0}) == ""


def test_the_row_is_in_the_stats_popup():
    renderer = _MODULE.read_text(encoding="utf-8")
    assert "${promptCacheRows(metrics)}" in renderer
