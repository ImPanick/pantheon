"""Every call that leaves the process is paced, or it is named (`P15-06`).

The row's `Verify:` is a checker, so most of this file breaks the checker in
specific ways and asserts it notices. The rest covers the two things that had to
be true before any of the routing was safe:

  * a local host must cost nothing, or the first person to profile a RAG index
    rips the limiter back out — correctly; and
  * the embedding client's 400-splitting retry must stop multiplying, because it
    is the one place in the product that can manufacture a burst from a steady
    workload.
"""
import ast
import asyncio
import pathlib
import shutil
import subprocess
import sys

import pytest

from src import rate_limiter as rl

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-outbound.py"


def run(args=(), cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(cwd / ".pantheon" / "check-outbound.py"), *args],
        cwd=cwd, capture_output=True, text=True)


# --------------------------------------------------------------------------
# The local-host policy — what made routing the local-first services possible
# --------------------------------------------------------------------------

@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "::1", "192.168.1.10", "10.0.0.4",
    "100.64.0.1",                 # tailnet — RFC 6598, NOT is_private
    "box.lan", "nas.local", "ollama", "searxng", "host.docker.internal",
])
def test_the_operators_own_machines_are_not_paced(host):
    """`D-2026-09-01-03`: internal comms are not a threat model. Pacing exists
    because a third party runs abuse detection; the operator's own box runs
    none, and the only thing a 0.25s floor buys there is 0.25s."""
    assert rl.host_is_local(host) is True
    assert rl.outbound.policy_for(host).min_interval == 0.0


@pytest.mark.parametrize("host", ["api.github.com", "huggingface.co",
                                  "example.com", "8.8.8.8", "ollama.com"])
def test_everything_else_still_is(host):
    assert rl.host_is_local(host) is False
    assert rl.outbound.policy_for(host).min_interval > 0


def test_a_tailnet_address_is_local_and_this_is_the_third_time():
    """`is_private` reports False for 100.64.0.0/10 (RFC 6598 shared space).
    That mistake has been made twice in this codebase already — once in the
    `Law 16` egress guard and once in `check-destinations.py`."""
    import ipaddress
    assert ipaddress.ip_address("100.64.0.1").is_private is False
    assert rl.host_is_local("100.64.0.1") is True


def test_an_explicit_policy_wins_over_the_local_shortcut(monkeypatch):
    """An operator who wrote a policy down meant it, even for a LAN name."""
    limiter = rl.OutboundHostLimiter({"gpu.lan": rl.HostPolicy(min_interval=5.0)})
    assert limiter.policy_for("gpu.lan").min_interval == 5.0


def test_a_local_host_is_still_OBSERVED():
    """What is dropped is the pre-emptive politeness, not the response handling.
    A local server that answers 429 is a real signal from a real server."""
    limiter = rl.OutboundHostLimiter()
    limiter.observe("localhost", 429, {"Retry-After": "120"})
    assert limiter.blocked_for("localhost") > 100


def test_pacing_a_local_endpoint_costs_nothing_measurable():
    """The concrete claim: a 5,000-chunk index is 625 batches, and at the
    DEFAULT policy that would be over two and a half minutes of pure sleeping."""
    limiter = rl.OutboundHostLimiter()
    import time
    start = time.monotonic()
    for _ in range(200):
        limiter.acquire("localhost")
    assert time.monotonic() - start < 0.5
    assert rl.HostPolicy().min_interval * 625 > 150   # what it would have cost


# --------------------------------------------------------------------------
# The embedding fan-out amplifier
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.headers = {}
        self._payload = payload or {"data": [{"embedding": [0.0], "index": 0}]}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=self)


class _CountingClient:
    """Answers 400 to anything longer than `ok_len`, counting every request."""

    def __init__(self, ok_len=0):
        self.calls = []
        self.ok_len = ok_len

    def post(self, url, headers=None, json=None):
        batch = (json or {}).get("input", [])
        self.calls.append(list(batch))
        if any(len(t) > self.ok_len for t in batch):
            return _Resp(400)
        return _Resp(200, {"data": [{"embedding": [0.0], "index": i}
                                    for i in range(len(batch))]})


def _client(monkeypatch, counting):
    from src import embeddings
    c = embeddings.EmbeddingClient(url="http://localhost:11434/v1/embeddings")
    c._client = counting
    return c


def test_a_rejected_batch_splits_ONCE_and_then_trims(monkeypatch):
    """THE AMPLIFIER. A 400 usually means one item is too long, and splitting
    finds it — turning ONE request into NINE. The recursion had no depth limit,
    so a batch whose items were ALL too long produced the maximum fan-out every
    time, during a RAG index, when thousands of batches are in flight."""
    from src import embeddings
    counting = _CountingClient(ok_len=5)
    client = _client(monkeypatch, counting)
    client._max_chars = 3
    client.encode(["x" * 50] * 8)
    # 1 batch + 8 singles + 8 trimmed retries. Without the depth bound the
    # singles would split again; with it, a single that still 400s is trimmed.
    assert len(counting.calls) <= 1 + 8 + 8, f"fan-out was {len(counting.calls)}"
    assert embeddings._MAX_SPLIT_DEPTH == 1


def test_the_split_depth_is_what_bounds_it(monkeypatch):
    """Raising the bound raises the fan-out — which is the proof the constant is
    doing the work, rather than some other limit happening to hold."""
    from src import embeddings
    counting = _CountingClient(ok_len=5)
    client = _client(monkeypatch, counting)
    client._max_chars = 3
    client._batch_size = 8
    client.encode(["x" * 50] * 8)
    bounded = len(counting.calls)

    monkeypatch.setattr(embeddings, "_MAX_SPLIT_DEPTH", 0)
    counting2 = _CountingClient(ok_len=5)
    client2 = _client(monkeypatch, counting2)
    client2._max_chars = 3
    client2._batch_size = 8
    client2.encode(["x" * 50] * 8)
    assert len(counting2.calls) < bounded, "the depth bound changed nothing"


def test_every_embedding_request_passes_the_limiter(monkeypatch):
    seen = []
    monkeypatch.setattr(rl.outbound, "acquire",
                        lambda host, **kw: seen.append(host) or 0.0)
    counting = _CountingClient(ok_len=10_000)
    client = _client(monkeypatch, counting)
    client.encode(["short"] * 24)
    assert len(seen) == len(counting.calls) > 1
    assert set(seen) == {"localhost"}


def test_the_embedding_endpoints_own_429_is_heard(monkeypatch):
    """`O7`. Every test above proved the request was PACED; none proved the
    response was observed, so deleting the `observe` changed nothing any of them
    could see. Acquiring without observing is half a limiter: it spaces requests
    out and then ignores the one signal that says stop."""
    limiter = rl.OutboundHostLimiter()
    monkeypatch.setattr(rl, "outbound", limiter)

    class _Limited:
        def post(self, url, headers=None, json=None):
            return _Resp(429)
    client = _client(monkeypatch, _Limited())
    with pytest.raises(Exception):
        client.encode(["hello"])
    assert limiter.blocked_for("localhost") > 0, \
        "the endpoint said 429 and nothing recorded it"


def test_a_cooled_embedding_endpoint_fails_loudly_rather_than_hanging(monkeypatch):
    def _boom(host, **kw):
        raise rl.OutboundRateLimited(host, 60.0, "cooling")
    monkeypatch.setattr(rl.outbound, "acquire", _boom)
    client = _client(monkeypatch, _CountingClient(ok_len=10_000))
    with pytest.raises(RuntimeError, match="cooldown"):
        client.encode(["hello"])


# --------------------------------------------------------------------------
# The unbounded search fan-out
# --------------------------------------------------------------------------

def test_the_research_search_fan_out_is_bounded():
    """A round can generate up to 25 queries, each walking the whole provider
    chain, and they were launched in one unbounded `gather`. The extraction
    path ten lines below had a semaphore all along.

    Measured, not read. An earlier version of this asserted the word
    `Semaphore` appeared twice in the function and that the constructor clamped
    its argument — both of which stay true when the semaphore is constructed
    with 9999, which is the defect.
    """
    from src.deep_research import DeepResearcher

    researcher = DeepResearcher(llm_endpoint="http://localhost/x", llm_model="m",
                                search_concurrency=3)
    live = {"now": 0, "peak": 0}

    async def _fake_search(query):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.01)
        live["now"] -= 1
        return []

    researcher._search = _fake_search
    asyncio.run(researcher._search_and_extract([f"q{i}" for i in range(25)], "why"))
    assert live["peak"] <= 3, f"{live['peak']} searches ran at once against a bound of 3"
    assert live["peak"] > 1, "the bound serialised everything, which is a different bug"


# --------------------------------------------------------------------------
# paced_http — the wrapper that makes the polite version the short one
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status=200, headers=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self.text = text


class _FakeClient:
    def __init__(self, response=None, boom=None):
        self.response = response or _FakeResponse()
        self.boom = boom
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.boom:
            raise self.boom
        return self.response

    async def aclose(self):
        pass


def test_paced_http_acquires_then_observes(monkeypatch):
    from src import paced_http
    order = []

    async def _acq(host, **kw):
        order.append(("acquire", host))
        return 0.0
    monkeypatch.setattr(rl.outbound, "acquire_async", _acq)
    monkeypatch.setattr(rl.outbound, "observe",
                        lambda h, s, hd=None, **kw: order.append(("observe", h, s)))
    client = _FakeClient(_FakeResponse(200))
    asyncio.run(paced_http.get("https://api.example.test/x", client=client))
    assert order == [("acquire", "api.example.test"),
                     ("observe", "api.example.test", 200)]


def test_a_success_resets_the_ladder_but_NOT_the_servers_deadline(monkeypatch):
    """`B36`. The half that gets dropped when the ritual is written out by hand
    is observing a SUCCESS at all — it clears the escalation ladder, so the next
    penalty starts from the base cooldown rather than from wherever the last bad
    run left it.

    What it deliberately does not do is clear a hard cooldown. The limiter's
    docstring claimed it did, for as long as the file has existed, and writing
    this test against the docstring is how that was found. A `blocked_until`
    comes from the server's own `Retry-After`; a 200 arriving while we believe
    the host is blocked means somebody bypassed `acquire`, and letting that
    erase the block would let the one caller who skips the gate un-ban the host
    for everybody else.
    """
    from src import paced_http
    limiter = rl.OutboundHostLimiter()
    limiter.observe("api.example.test", 429, {"Retry-After": "60"})
    limiter.observe("api.example.test", 429, {"Retry-After": "60"})
    assert limiter.snapshot()["api.example.test"]["consecutive_429"] == 2
    monkeypatch.setattr(rl, "outbound", limiter)

    # The gate is stubbed, not the feedback: a real `acquire_async` would
    # correctly sit through the cooldown this test just created, which is a
    # different behaviour from the one under test.
    async def _pass(host, **kw):
        return 0.0
    monkeypatch.setattr(limiter, "acquire_async", _pass)

    asyncio.run(paced_http.get("https://api.example.test/x",
                               client=_FakeClient(_FakeResponse(200))))
    state = limiter.snapshot()["api.example.test"]
    assert state["consecutive_429"] == 0, "the ladder was not reset"
    assert state["blocked_for"] > 0, "a 200 erased the server's own deadline"

    # `succeeded()` is the explicit way to drop everything, for the `penalise`
    # path where the failure carried no expiry to wait out.
    limiter.succeeded("api.example.test")
    assert limiter.blocked_for("api.example.test") == 0


def test_the_body_is_only_read_when_the_status_suggests_a_limit(monkeypatch):
    """GitHub's primary rate limit is a 403 whose BODY is the only place that
    says so. Reading every response's text to find that would materialise
    bodies this module has no other reason to touch."""
    from src import paced_http
    seen = {}
    monkeypatch.setattr(rl.outbound, "observe",
                        lambda h, s, hd=None, *, body_hint="": seen.update(hint=body_hint))

    # A COUNTER, not a raise: `_observe` wraps the body read in
    # `except Exception`, and an `AssertionError` is an Exception — so the
    # obvious exploding-property trick is swallowed by the very guard that makes
    # this safe, and the mutation survived it.
    reads = {"n": 0}

    class _Counting:
        status_code = 200
        headers = {}

        @property
        def text(self):
            reads["n"] += 1
            return "body"

    asyncio.run(paced_http.get("https://api.example.test/x",
                               client=_FakeClient(_Counting())))
    assert seen["hint"] == ""
    assert reads["n"] == 0, "the body was read on a 200"
    asyncio.run(paced_http.get("https://api.example.test/x",
                               client=_FakeClient(_FakeResponse(403, text="rate limit"))))
    assert "rate limit" in seen["hint"]


def test_a_transport_failure_still_slows_the_host_down(monkeypatch):
    from src import paced_http
    limiter = rl.OutboundHostLimiter()
    monkeypatch.setattr(rl, "outbound", limiter)
    # `acquire` creates the state row AND advances `next_allowed_at` by the
    # pacing gap on its own, so both "the host appears in the snapshot" and a
    # naive "next_allowed_at moved" pass with `note_failure` deleted. The
    # distinguishing effect is the SIZE: the default gap is 0.25s, and
    # `note_failure` pushes it a further 5s out.
    import time
    with pytest.raises(OSError):
        asyncio.run(paced_http.get("https://api.example.test/x",
                                   client=_FakeClient(boom=OSError("no route"))))
    remaining = limiter._st("api.example.test").next_allowed_at - time.monotonic()
    assert remaining > 1.0, (
        f"a host refusing connections is only being held off for {remaining:.2f}s — "
        "that is ordinary pacing, not a transport-failure backoff"
    )


# --------------------------------------------------------------------------
# The checker
# --------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    (dst / ".pantheon").mkdir(parents=True)
    (dst / "src").mkdir()
    shutil.copy2(CHECKER, dst / ".pantheon" / "check-outbound.py")
    (dst / "app.py").write_text(
        "import httpx\n"
        "async def fine():\n"
        "    from src import paced_http\n"
        "    return await paced_http.get('https://api.example.test/x')\n",
        encoding="utf-8",
    )
    return dst


def test_the_real_tree_calls_no_policed_host_unpaced():
    r = run(["--quiet"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_real_tree_is_within_the_budget_ci_pins():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check-outbound.py --max" in ci, "the checker is not in CI"
    budget = int(ci.split("check-outbound.py --max")[1].split()[0])
    r = run(["--max", str(budget), "--quiet"])
    assert r.returncode == 0, \
        f"the tree exceeds the budget CI pins ({budget}):\n{r.stdout}{r.stderr}"


def test_fixture_baseline_passes(repo):
    assert run(["--quiet"], repo).returncode == 0, run([], repo).stdout


def test_an_unpaced_call_to_a_policed_host_fails_with_no_budget(repo):
    """The one rule with no headroom: those policies exist only because those
    hosts have already throttled this product."""
    (repo / "app.py").write_text(
        "import httpx\n"
        "def grab():\n"
        "    return httpx.get('https://huggingface.co/api/models', timeout=5)\n",
        encoding="utf-8",
    )
    r = run(["--max", "999"], repo)
    assert r.returncode == 1 and "POLICED" in r.stdout


def test_the_policed_rule_is_scoped_to_the_FUNCTION_not_the_file(repo):
    """The first version searched the whole file, so one mention of
    `html.duckduckgo.com` in a 700-line provider chain flagged the unrelated
    Google, Tavily and Serper calls beside it — 57 findings, almost none of them
    about the host named."""
    (repo / "app.py").write_text(
        "import httpx\n"
        "def duck():\n"
        "    from src import paced_http\n"
        "    return paced_http.get_sync('https://html.duckduckgo.com/html/')\n"
        "def unrelated():\n"
        "    return httpx.get('https://api.tavily.test/search', timeout=5)\n",
        encoding="utf-8",
    )
    r = run(["--max", "999"], repo)
    assert r.returncode == 0, r.stdout


def test_the_budget_fails_when_the_count_grows(repo):
    (repo / "app.py").write_text(
        "import httpx\n"
        "def grab():\n"
        "    return httpx.get('https://api.example.test/x', timeout=5)\n",
        encoding="utf-8",
    )
    assert run(["--max", "0"], repo).returncode == 1
    assert run(["--max", "1"], repo).returncode == 0


def test_a_dict_lookup_is_not_a_network_call(repo):
    """`_HTTPCORE_TO_HTTPX_EXC.get(exc)` contains the word `httpx` and is a
    dict access; `self._sessions.get(id)` is a dict too. Both were false
    positives on the first run."""
    (repo / "app.py").write_text(
        "_HTTPCORE_TO_HTTPX_EXC = {}\n"
        "class S:\n"
        "    def look(self, k):\n"
        "        return _HTTPCORE_TO_HTTPX_EXC.get(k) or self._sessions.get(k)\n",
        encoding="utf-8",
    )
    r = run(["--max", "0"], repo)
    assert r.returncode == 0, r.stdout


def test_a_bare_urlopen_counts(repo):
    (repo / "app.py").write_text(
        "import urllib.request\n"
        "def grab():\n"
        "    return urllib.request.urlopen('https://api.example.test/x')\n",
        encoding="utf-8",
    )
    assert run(["--max", "0"], repo).returncode == 1


def test_a_function_that_acquires_is_paced(repo):
    (repo / "app.py").write_text(
        "import httpx\n"
        "from src.rate_limiter import outbound\n"
        "def grab():\n"
        "    outbound.acquire('api.example.test')\n"
        "    return httpx.get('https://api.example.test/x', timeout=5)\n",
        encoding="utf-8",
    )
    assert run(["--max", "0"], repo).returncode == 0
