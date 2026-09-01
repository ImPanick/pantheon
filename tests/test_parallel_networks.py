"""Two segments, and a run told to use one cannot reach the other (`P16-16`).

The owner's north star includes automating things on *"my network (even my
parallel networks etc)"*. Today `model_discovery` returns one flat list of
hosts — loopback, `host.docker.internal`, `LLM_HOSTS`, every Tailscale peer —
with no notion of which network anything is on, so there is nothing to scope.

Several segments is not a bigger scan. A printer VLAN, a lab subnet and the
production network have different reachability, different credentials and
different trust; flattening them means an agent asked to tidy the lab can reach
production.

Three properties are tested, and the third is the one that makes it a boundary
rather than a filter:

  1. Nothing declared changes nothing. The shipped state is today's behaviour.
  2. Declaring names classifies hosts and tags discovery.
  3. Inside a scope, an out-of-scope host is refused **at every path Pantheon
     opens itself** — and an unclassifiable host is refused too, because "I
     could not tell" is not a reason to allow reach.
"""
import ipaddress

import pytest

from src import networks as nw

LAB = {"name": "lab", "cidrs": ["10.9.0.0/24"], "hosts": ["lab-gpu.lan"],
       "trust": "limited"}
PROD = {"name": "prod", "cidrs": ["10.20.0.0/16"], "hosts": ["prod-llm.internal"],
        "trust": "trusted"}


@pytest.fixture
def declared(monkeypatch):
    def declare(*nets):
        monkeypatch.setattr(nw, "_raw_networks", lambda: list(nets))
    return declare


@pytest.fixture(autouse=True)
def _no_scope():
    token = nw._scope.set(None)
    yield
    nw._scope.reset(token)


# --- 1. nothing declared changes nothing ----------------------------------

def test_the_shipped_state_declares_nothing():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["networks"] == []


def test_with_nothing_declared_everything_is_allowed(monkeypatch):
    """`Law 16` is about defaults, not capability. An install that has named no
    networks must behave exactly as it did before this module existed."""
    monkeypatch.setattr(nw, "_raw_networks", lambda: [])
    assert nw.network_for("10.9.0.5") is None
    assert nw.host_allowed("anything.at.all") is True
    assert nw.hosts_in_scope() is None
    nw.require_host("10.20.0.9")     # must not raise


# --- 2. names classify ----------------------------------------------------

def test_hosts_resolve_to_the_network_that_contains_them(declared):
    declared(LAB, PROD)
    assert nw.network_for("10.9.0.5") == "lab"
    assert nw.network_for("lab-gpu.lan") == "lab"
    assert nw.network_for("10.20.7.3") == "prod"
    assert nw.network_for("8.8.8.8") is None


def test_trust_is_per_network(declared):
    declared(LAB, PROD)
    assert nw.trust_for("10.9.0.5") == "limited"
    assert nw.trust_for("10.20.7.3") == "trusted"


def test_a_bare_name_matches_only_by_exact_listing(declared):
    """Membership must not depend on DNS answered by whichever network we
    happen to be sitting on — that ambiguity is what this module removes."""
    declared(LAB)
    assert nw.network_for("lab-gpu.lan") == "lab"
    assert nw.network_for("some-other-host.lan") is None


def test_declaration_order_decides_an_overlap(declared):
    """Stated rather than sorted: "most specific wins" quietly reorders what
    someone wrote, and the surprise lands later."""
    narrow = {"name": "narrow", "cidrs": ["10.9.0.0/28"]}
    broad = {"name": "broad", "cidrs": ["10.9.0.0/16"]}
    declared(narrow, broad)
    assert nw.network_for("10.9.0.1") == "narrow"
    declared(broad, narrow)
    assert nw.network_for("10.9.0.1") == "broad"


def test_a_disabled_network_classifies_nothing(declared):
    declared({**LAB, "enabled": False})
    assert nw.network_for("10.9.0.5") is None
    assert len(nw.declared_networks(include_disabled=True)) == 1


def test_an_unparseable_cidr_is_dropped_not_fatal(declared):
    declared({"name": "typo", "cidrs": ["10.9.0.0/24", "not-a-cidr", "999.1.1.1/8"]})
    assert nw.network_for("10.9.0.5") == "typo"


# --- 3. the boundary ------------------------------------------------------

def test_a_scoped_run_cannot_reach_the_other_segment(declared):
    """The row's Verify, stated exactly: an operator declares two segments and
    the agent can be told to act on one without gaining reach into the other."""
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        assert nw.host_allowed("10.9.0.5") is True
        assert nw.host_allowed("10.20.7.3") is False
        with pytest.raises(nw.NetworkScopeViolation):
            nw.require_host("10.20.7.3")


def test_an_unclassifiable_host_is_refused_inside_a_scope(declared):
    """"I could not tell which network that is" is not a reason to permit
    reach. Someone who named two segments and asked for one did not mean "and
    also anything I forgot to describe"."""
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        assert nw.host_allowed("8.8.8.8") is False
        assert nw.host_allowed("example.com") is False


def test_the_refusal_says_what_and_why(declared):
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        with pytest.raises(nw.NetworkScopeViolation) as e:
            nw.require_host("10.20.7.3")
    message = str(e.value)
    assert "10.20.7.3" in message and "prod" in message and "lab" in message


def test_nesting_narrows_and_never_widens(declared):
    """A scope that can be widened from inside is not a scope."""
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        with nw.scoped_to(["lab", "prod"]):
            assert nw.host_allowed("10.20.7.3") is False, "an inner scope widened the outer one"
            assert nw.host_allowed("10.9.0.5") is True
        assert nw.host_allowed("10.20.7.3") is False


def test_the_scope_is_restored_even_when_the_body_raises(declared):
    declared(LAB, PROD)
    with pytest.raises(ValueError):
        with nw.scoped_to(["lab"]):
            raise ValueError("boom")
    assert nw.current_scope() is None
    assert nw.host_allowed("10.20.7.3") is True


def test_the_scope_does_not_leak_between_async_tasks(declared):
    """ContextVars follow a task. Two concurrent runs must not read each
    other's scope, or "scoped to the lab" means nothing under load."""
    import asyncio
    declared(LAB, PROD)

    async def scoped(name, seen):
        with nw.scoped_to([name]):
            await asyncio.sleep(0)
            seen[name] = sorted(nw.current_scope())

    async def main():
        seen = {}
        await asyncio.gather(scoped("lab", seen), scoped("prod", seen))
        return seen

    seen = asyncio.run(main())
    assert seen == {"lab": ["lab"], "prod": ["prod"]}


# --- the boundary holds on the paths Pantheon opens itself ----------------

def test_the_url_gate_refuses_an_out_of_scope_host(declared):
    from src.url_safety import check_outbound_url
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        ok, reason = check_outbound_url("http://10.20.7.3:8000/v1/models",
                                        resolver=lambda h: ["10.20.7.3"])
        assert ok is False
        assert "scope" in reason or "prod" in reason


def test_the_url_gate_is_checked_before_dns(declared):
    """Refusing after a lookup has told the other network's resolver we asked
    is a boundary that leaks the question it exists to prevent."""
    declared(LAB, PROD)
    resolved = []
    with nw.scoped_to(["lab"]):
        from src.url_safety import check_outbound_url
        check_outbound_url("http://prod-llm.internal/x",
                           resolver=lambda h: resolved.append(h) or ["10.20.7.3"])
    assert resolved == [], "DNS was consulted for a host the scope had already refused"


def test_the_limiter_refuses_an_out_of_scope_host(declared):
    """`P15`'s limiter is the one place every deliberately-paced outbound call
    passes through, which makes it a cheap second layer."""
    from src.rate_limiter import OutboundHostLimiter
    declared(LAB, PROD)
    limiter = OutboundHostLimiter()
    with nw.scoped_to(["lab"]):
        with pytest.raises(nw.NetworkScopeViolation):
            limiter.acquire("10.20.7.3")
        limiter.acquire("10.9.0.5")     # in scope, must not raise


def test_outbound_fetch_refuses_an_out_of_scope_host(declared):
    import httpx
    from src.outbound_fetch import _resolve_public_ips
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        with pytest.raises(httpx.RequestError) as e:
            _resolve_public_ips("http://10.20.7.3/x")
    assert "scope" in str(e.value).lower()


# --- discovery ------------------------------------------------------------

def test_discovery_scans_only_the_networks_in_scope(declared):
    declared(LAB, PROD)
    with nw.scoped_to(["lab"]):
        assert nw.hosts_in_scope() == ["lab-gpu.lan"]
    with nw.scoped_to(["prod"]):
        assert nw.hosts_in_scope() == ["prod-llm.internal"]


def test_cidrs_are_never_expanded_into_a_sweep(declared):
    """A /16 is 65,536 addresses. Turning a declaration into a scan is how
    "discover my networks" becomes a port scanner someone's IDS reports."""
    declared({"name": "big", "cidrs": ["10.0.0.0/8"], "hosts": ["one.lan"]})
    assert nw.hosts_in_scope() == ["one.lan"]


def test_discovered_endpoints_carry_their_network(declared):
    """A model list that cannot say which network a server is on is how "the
    lab GPU" and "the production GPU" become one dropdown."""
    import src.model_discovery as md
    declared(LAB, PROD)
    assert md._network_for("10.9.0.5") == "lab"
    assert md._network_for("10.20.7.3") == "prod"
    src = (md.__file__)
    assert '"network": _network_for(host)' in open(src, encoding="utf-8").read()


def test_declaring_a_network_does_not_remove_localhost(declared, monkeypatch):
    """Declaring a lab subnet is not a statement that loopback stopped
    existing. With no scope in force, declarations ADD."""
    import src.model_discovery as md
    declared(LAB)
    disc = md.ModelDiscovery.__new__(md.ModelDiscovery)
    disc.default_host = "localhost"
    disc._extra_ports = set()
    hosts = disc._get_hosts()
    assert "lab-gpu.lan" in hosts
    assert "localhost" in hosts


def test_a_scoped_discovery_does_not_include_localhost(declared, monkeypatch):
    """...but inside a scope it does not, because loopback is not the lab."""
    import src.model_discovery as md
    declared(LAB)
    disc = md.ModelDiscovery.__new__(md.ModelDiscovery)
    disc.default_host = "localhost"
    disc._extra_ports = set()
    with nw.scoped_to(["lab"]):
        hosts = disc._get_hosts()
    assert hosts == ["lab-gpu.lan"]


# --- honesty about the limit ---------------------------------------------

def test_the_module_says_plainly_what_it_does_not_enforce():
    """A boundary described as tighter than it is, is worse than one described
    accurately — people plan around the description. A shell tool running
    `curl` reaches whatever the process has a route to, and stopping that needs
    a network namespace, not a Python function."""
    doc = nw.__doc__ or ""
    assert "not** an OS-level control" in doc or "not an OS-level control" in doc
    assert "curl" in doc
    assert "P16-20" in doc
