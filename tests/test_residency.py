"""One generative model resident at a time (models/residency.py), against the synthetic server."""

from home_manager.core.jobs import Work
from home_manager.models import residency
from home_manager.models.model_client import request_completion
from home_manager.models.vision import VisionConfig


def native(local_model, loaded=(), types=None):
    local_model["native"] = {"loaded": set(loaded), "types": types or {}, "calls": []}
    return local_model["native"]


def config(local_model, model):
    return VisionConfig(base_url=local_model["config"].base_url, model=model)


def chat(local_model, model):
    return request_completion(config(local_model, model), {"messages": [{"role": "user", "content": "hi"}]})


def test_loads_when_nothing_is_loaded(local_model):
    state = native(local_model)
    chat(local_model, "synthetic-vision")
    assert state["calls"] == [("load", "synthetic-vision"), ("chat", "synthetic-vision")]


def test_does_nothing_when_the_target_is_already_the_only_model(local_model):
    state = native(local_model, loaded={"synthetic-vision"})
    chat(local_model, "synthetic-vision")
    assert state["calls"] == [("chat", "synthetic-vision")]


def test_unloads_a_different_model_before_loading(local_model):
    state = native(local_model, loaded={"synthetic-vision"})
    work = Work.detached()
    stages = []
    work.report = lambda value: stages.append(value["stage"])
    request_completion(config(local_model, "synthetic-reasoning"), {"messages": [{"role": "user", "content": "hi"}]}, work)
    assert state["calls"] == [("unload", "synthetic-vision"), ("load", "synthetic-reasoning"), ("chat", "synthetic-reasoning")]
    assert stages[:2] == ["unloading_model", "loading_model"]


def test_unloads_others_but_keeps_a_loaded_target(local_model):
    state = native(local_model, loaded={"synthetic-vision", "synthetic-reasoning"})
    chat(local_model, "synthetic-reasoning")
    assert state["calls"] == [("unload", "synthetic-vision"), ("chat", "synthetic-reasoning")]


def test_skips_embedding_models(local_model):
    state = native(local_model, loaded={"nomic-embed", "synthetic-vision"}, types={"nomic-embed": "embedding"})
    chat(local_model, "synthetic-vision")
    assert state["calls"] == [("chat", "synthetic-vision")]
    assert "nomic-embed" in state["loaded"]


def test_falls_back_to_jit_when_the_native_api_is_missing(local_model):
    # The fake server answers 404 for /api/v1/models unless "native" is set.
    assert chat(local_model, "synthetic-vision")
    assert local_model["requests"][-1]["model"] == "synthetic-vision"
    assert residency.hint()
    residency.configure(False)
    assert residency.hint() is None


def test_turned_off_leaves_loading_to_the_server(local_model):
    state = native(local_model, loaded={"synthetic-vision"})
    residency.configure(False)
    chat(local_model, "synthetic-reasoning")
    assert state["calls"] == [("chat", "synthetic-reasoning")]


def test_vision_then_reasoning_swaps_models_once(local_model):
    state = native(local_model)
    chat(local_model, "synthetic-vision")
    chat(local_model, "synthetic-reasoning")
    assert state["calls"] == [("load", "synthetic-vision"), ("chat", "synthetic-vision"),
                              ("unload", "synthetic-vision"), ("load", "synthetic-reasoning"), ("chat", "synthetic-reasoning")]
    assert state["loaded"] == {"synthetic-reasoning"}


def test_remote_servers_are_left_to_the_gpu_host(local_model):
    state = native(local_model)
    remote = VisionConfig(base_url="http://100.100.1.2:8766/v1", model="home-manager/vision")
    residency.ensure_loaded(remote, Work.detached())  # Never contacts the tailnet address.
    assert state["calls"] == []
