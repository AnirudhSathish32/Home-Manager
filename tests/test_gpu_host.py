"""Shared GPU relay (models/gpu_host.py) and the client's Model computer setting, with synthetic data only."""

from datetime import date, timedelta
import http.client
import json
import logging
import threading
import time

from pydantic import ValidationError
import pytest

from home_manager.app.manager import Manager
from home_manager.core.jobs import Work
from home_manager.library.scanner import ScanLimits
from home_manager.models import gpu_host, model_client
from home_manager.models.gpu_host import GpuHost, Handler, RelayServer, add_member, load_host, make_server, remove_member, save_host
from home_manager.models.model_client import check_connection, model_identity, request_completion, set_token
from home_manager.models.model_stream import read_completion
from home_manager.models.vision import ModelComputer, VisionConfig

MESSAGES = {"messages": [{"role": "user", "content": "SECRET-RECEIPT-TEXT"}]}


@pytest.fixture
def relay(tmp_path, local_model):
    control = tmp_path / "gpu"
    control.mkdir()
    (control / "vision.json").write_text(json.dumps({"base_url": "http://127.0.0.1:8766/v1", "model": "synthetic-vision"}))
    (control / "reasoning.json").write_text(json.dumps({"base_url": "http://127.0.0.1:8766/v1", "model": "synthetic-reasoning"}))
    config = load_host(control)
    config.upstream = local_model["config"].base_url
    save_host(control, config)
    token = add_member(control, "Mom")
    host = GpuHost(control, keepalive_seconds=0.1)
    servers = {}
    for loopback in (False, True):
        # Tests cannot bind a tailnet address; the member listener is built directly on loopback instead.
        server = RelayServer(("127.0.0.1", 0), Handler)
        server.gpu_host, server.loopback = host, loopback
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers["local" if loopback else "member"] = server
    state = {"host": host, "control": control, "token": token, "upstream": local_model,
             "member": f"http://127.0.0.1:{servers['member'].server_port}/v1",
             "local": f"http://127.0.0.1:{servers['local'].server_port}/v1"}
    try:
        yield state
    finally:
        for server in servers.values():
            server.shutdown()
            server.server_close()


def call(url, method, path, body=None, token=None):
    port = int(url.rsplit(":", 1)[1].split("/")[0])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
    return connection, connection.getresponse()


def as_member(monkeypatch, relay, token=None):
    """Treat the loopback member listener as the remote GPU computer, with the member's token."""
    monkeypatch.setattr(model_client, "is_remote", lambda config: True)
    set_token(relay["member"], token or relay["token"])


def test_members_need_a_valid_token(relay):
    for token in (None, "not-a-real-token-at-all"):
        connection, response = call(relay["member"], "GET", "/v1/models", token=token)
        assert response.status == 401
        connection.close()
    connection, response = call(relay["member"], "GET", "/v1/models", token=relay["token"])
    assert response.status == 200
    connection.close()


def test_only_hashes_are_stored_and_tokens_can_be_revoked(relay):
    saved = (relay["control"] / "gpu_host.json").read_text()
    assert relay["token"] not in saved and "Mom" in saved
    assert remove_member(relay["control"], "Mom")
    connection, response = call(relay["member"], "GET", "/v1/models", token=relay["token"])
    assert response.status == 401  # Revocation applies without restarting the relay.
    connection.close()


def test_testers_tokens_work_until_they_expire(relay, monkeypatch):
    token = add_member(relay["control"], "Friend", "tester")
    member = load_host(relay["control"]).members["Friend"]
    assert member.kind == "tester" and member.expires == date.today() + timedelta(days=gpu_host.TESTER_DAYS)
    connection, response = call(relay["member"], "GET", "/v1/models", token=token)
    assert response.status == 200
    connection.close()
    config = load_host(relay["control"])
    config.members["Friend"].expires = date.today() - timedelta(days=1)
    save_host(relay["control"], config)
    connection, response = call(relay["member"], "GET", "/v1/models", token=token)
    assert response.status == 401  # Expiry applies without restarting the relay.
    connection.close()
    with pytest.raises(ValueError):
        add_member(relay["control"], "Friend", "tester", date.today() - timedelta(days=1))


def test_hosts_saved_before_member_kinds_still_load(tmp_path):
    (tmp_path / "gpu_host.json").write_text(json.dumps({"members": {"Mom": "a" * 64}}))
    member = load_host(tmp_path).members["Mom"]
    assert (member.token_sha256, member.kind, member.expires) == ("a" * 64, "family", None)


def test_testers_wait_behind_the_family_without_starving():
    scheduler = gpu_host.Scheduler(max_skips=1)
    order = []
    first = scheduler.acquire("a", "me", "vision")
    threads = []
    for member, tester in (("Friend", True), ("Friend 2", True), ("Mom", False), ("Dad", False)):
        def run(member=member, tester=tester):
            ticket = scheduler.acquire("a", member, "vision", poll=0.05, tester=tester)
            order.append(member)
            scheduler.release(ticket)
        threads.append(threading.Thread(target=run))
        threads[-1].start()
        time.sleep(0.1)  # Queue in a known order.
    scheduler.release(first)
    for thread in threads:
        thread.join(timeout=5)
    # Mom goes ahead of both testers; having been skipped once, they may be skipped no more, so Dad waits.
    assert order == ["Mom", "Friend", "Friend 2", "Dad"]


@pytest.mark.parametrize("address, loopback", [("192.168.1.5", False), ("0.0.0.0", False), ("127.0.0.1", False),
                                               ("8.8.8.8", False), ("0.0.0.0", True), ("100.64.0.1", True)])
def test_refuses_non_tailnet_binds(relay, address, loopback):
    with pytest.raises(ValueError):
        make_server(relay["host"], address, 0, loopback)


@pytest.mark.parametrize("method, path", [("GET", "/api/v0/models"), ("POST", "/api/v1/models/load"), ("POST", "/api/v1/models/unload"),
                                          ("GET", "/status"), ("POST", "/v1/completions"), ("GET", "/v1/chat/completions")])
def test_only_the_listed_endpoints_are_available(relay, method, path):
    connection, response = call(relay["member"], method, path, {} if method == "POST" else None, relay["token"])
    assert response.status == 404
    connection.close()
    connection, response = call(relay["member"], "PUT", "/v1/models", {}, relay["token"])
    assert response.status == 501
    connection.close()


def test_role_aliases_map_to_the_owners_models(relay, monkeypatch):
    as_member(monkeypatch, relay)
    listing = check_connection(VisionConfig(base_url=relay["member"], model="home-manager/vision"))
    assert listing["model_listed"]
    assert listing["available_models"] == ["home-manager/reasoning", "home-manager/reviewer", "home-manager/vision"]
    text = request_completion(VisionConfig(base_url=relay["member"], model="home-manager/reasoning"), dict(MESSAGES))
    assert json.loads(text) == relay["upstream"]["output"]
    assert relay["upstream"]["requests"][-1]["model"] == "synthetic-reasoning"
    assert "Authorization" not in relay["upstream"]["headers"]  # The member's token stops at the relay.
    with pytest.raises(ValueError):
        request_completion(VisionConfig(base_url=relay["member"], model="some-other-model"), dict(MESSAGES))


def test_decision_requests_relay_only_for_the_decision_role(relay, monkeypatch):
    from home_manager.models import decisions
    from home_manager.models.decisions import DecisionConfig
    state = relay["upstream"]
    state["decide"] = lambda path, body: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "A", "logprobs": [
        {"token": "A", "logprob": -0.1, "top_logprobs": [{"token": "A", "logprob": -0.1}, {"token": "B", "logprob": -2.4}]}]}]}]}
    as_member(monkeypatch, relay)
    member = DecisionConfig(provider="lmstudio", base_url=relay["member"], model="home-manager/decision")
    with pytest.raises(ValueError):  # The owner has not shared a decision model yet.
        decisions.support(member, [("total: 1.00", ["Total 1.00"])])
    (relay["control"] / "decision.json").write_text(json.dumps({"provider": "lmstudio", "base_url": "http://127.0.0.1:1234/v1", "model": "synthetic-reasoning"}))
    assert decisions.support(member, [("total: 1.00", ["Total 1.00"])])[0] > 0.8
    assert state["decisions"][-1] == ("/v1/responses", {**state["decisions"][-1][1], "model": "synthetic-reasoning"})
    # Another role's model can't be asked on /v1/responses.
    other = DecisionConfig(provider="lmstudio", base_url=relay["member"], model="home-manager/reasoning")
    with pytest.raises(ValueError):
        decisions.support(other, [("total: 1.00", ["Total 1.00"])])


def test_the_owners_app_uses_loopback_without_a_token(relay):
    state = relay["upstream"]
    state["native"] = {"loaded": {"synthetic-vision"}, "types": {}, "calls": []}
    text = request_completion(VisionConfig(base_url=relay["local"], model="synthetic-reasoning"), dict(MESSAGES))
    assert json.loads(text) == state["output"]
    # The relay switched models once; the app saw the relay manages residency and did not.
    assert state["native"]["calls"] == [("unload", "synthetic-vision"), ("load", "synthetic-reasoning"), ("chat", "synthetic-reasoning")]


def test_rejected_token_reads_as_a_shared_gpu_problem(relay, monkeypatch):
    as_member(monkeypatch, relay, token="x" * 43)
    with pytest.raises(ValueError, match="shared GPU token was rejected"):
        request_completion(VisionConfig(base_url=relay["member"], model="home-manager/vision"), dict(MESSAGES))


def test_concurrent_clients_are_serialised_and_keepalives_ignored(relay, monkeypatch):
    state = relay["upstream"]
    state["response_gate"] = threading.Event()
    as_member(monkeypatch, relay)
    first = {}
    thread = threading.Thread(target=lambda: first.setdefault("text", request_completion(
        VisionConfig(base_url=relay["member"], model="home-manager/vision"), dict(MESSAGES))))
    thread.start()
    deadline = time.monotonic() + 5
    while not state["requests"] and time.monotonic() < deadline:
        time.sleep(0.02)
    connection, response = call(relay["member"], "POST", "/v1/chat/completions",
                                {**MESSAGES, "model": "home-manager/reasoning", "stream": True}, relay["token"])
    assert response.status == 200
    assert response.readline().startswith(b": queued 1")  # Waiting behind the first request.
    assert len(state["requests"]) == 1  # The second has not reached LM Studio.
    state["response_gate"].set()
    text, _ = read_completion(response, Work.detached())
    connection.close()
    thread.join(timeout=10)
    assert json.loads(text) == json.loads(first["text"]) == state["output"]
    assert [request["model"] for request in state["requests"]] == ["synthetic-vision", "synthetic-reasoning"]


def test_scheduler_prefers_the_loaded_model_without_starving():
    scheduler = gpu_host.Scheduler(max_skips=1)
    order = []
    first = scheduler.acquire("a", "me", "vision")
    threads = []
    for model in ("b", "a", "a"):
        def run(model=model):
            ticket = scheduler.acquire(model, "me", model, poll=0.05)
            order.append(model)
            scheduler.release(ticket)
        threads.append(threading.Thread(target=run))
        threads[-1].start()
        time.sleep(0.1)  # Queue in a known order.
    scheduler.release(first)
    for thread in threads:
        thread.join(timeout=5)
    assert order == ["a", "b", "a"]  # One "a" jumps ahead of "b"; then "b" may be skipped no more.


def test_no_request_body_is_logged(relay, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="home_manager.gpu_host")
    as_member(monkeypatch, relay)
    request_completion(VisionConfig(base_url=relay["member"], model="home-manager/reasoning"), dict(MESSAGES))
    deadline = time.monotonic() + 5  # The relay logs once LM Studio closes the stream, just after the client finishes.
    while "Mom — reasoning" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "Mom — reasoning" in caplog.text
    assert "SECRET-RECEIPT-TEXT" not in caplog.text and "LOCAL TEST CAFE" not in caplog.text


def test_model_identity_works_through_the_relay(relay, monkeypatch):
    as_member(monkeypatch, relay)
    fingerprint, metadata = model_identity(VisionConfig(base_url=relay["member"], model="home-manager/vision"))
    assert fingerprint and metadata["listing"]["id"] == "home-manager/vision"


# Client side: the Model computer setting ---------------------------------------------------------

@pytest.mark.parametrize("url", ["http://100.100.1.2:8766/v1", "http://gpu-pc.tailnet-name.ts.net:8766/v1"])
def test_tailnet_endpoints_are_accepted(url):
    assert ModelComputer(provider="family_gpu", gpu_host_url=url).gpu_host_url == url
    assert VisionConfig(base_url=url, model="home-manager/vision").base_url == url  # Run options saved while using it.


@pytest.mark.parametrize("url", ["http://192.168.1.2:8766/v1", "https://100.100.1.2:8766/v1", "http://8.8.8.8:8766/v1",
                                 "http://example.com:8766/v1", "http://100.100.1.2/v1", "http://100.100.1.2:8766/other",
                                 "http://127.0.0.1:8766/v1", "http://evil.ts.net.example.com:8766/v1"])
def test_public_and_lan_endpoints_are_rejected(url):
    with pytest.raises(ValidationError):
        ModelComputer(provider="family_gpu", gpu_host_url=url)


def test_family_gpu_setting_points_models_at_roles(tmp_path):
    (tmp_path / "control").mkdir()
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        url = "http://100.100.1.2:8766/v1"
        with pytest.raises(ValueError, match="token"):
            manager.configure_model_computer(ModelComputer(provider="family_gpu", gpu_host_url=url))
        state = manager.configure_model_computer(ModelComputer(provider="family_gpu", gpu_host_url=url), token="t" * 43)
        assert state["token_set"] and "t" * 43 not in json.dumps(manager.settings())
        assert (manager.vision.base_url, manager.vision.model) == (url, "home-manager/vision")
        assert (manager.reasoning_config.base_url, manager.reasoning_config.model) == (url, "home-manager/reasoning")
        assert manager.settings()["vision"]["base_url"] == "http://127.0.0.1:1234/v1"  # This PC's own settings are kept.
        assert model_client._headers(manager.vision, {})["Authorization"] == "Bearer " + "t" * 43
        with pytest.raises(ValueError, match="Model computer"):
            manager.configure_vision(VisionConfig(base_url=url, model="x"))
        manager.configure_model_computer(ModelComputer(provider="local", gpu_host_url=url))
        assert manager.vision.base_url == "http://127.0.0.1:1234/v1"
        assert model_client._headers(VisionConfig(base_url=url), {}) == {}
    finally:
        manager.close()
