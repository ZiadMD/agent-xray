"""A primary model that fails with a fallback behind it (the crew's Groq -> Gemini setup)."""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import START, StateGraph

import basic_fake
from conftest import XRay


class AuthError(RuntimeError):
    pass


class FailingModel(basic_fake.ScriptedChatModel):
    """Raises as soon as it is asked for output, like a provider rejecting the key."""

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise AuthError("401 invalid api key")

    def _stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AuthError("401 invalid api key")
        yield  # pragma: no cover


class State(TypedDict, total=False):
    text: str


def build(model: Any) -> Any:
    def talk(state: State) -> dict[str, Any]:
        return {"text": str(model.invoke([HumanMessage(content="hi")]).content)}

    graph = StateGraph(State)
    graph.add_node("talk", talk)
    graph.add_edge(START, "talk")
    return graph.compile(name="fallback_demo")


def test_fallback_recovers_and_x_ray_shows_both(xray: XRay) -> None:
    primary = FailingModel(replies=["never"], model_name="primary-down")
    backup = basic_fake.ScriptedChatModel(
        replies=["answer from the backup model"], model_name="backup"
    )
    result = xray.wrap(build(primary.with_fallbacks([backup]))).invoke({})
    assert result["text"] == "answer from the backup model"

    events = xray.only_run()
    assert events[-1].data.status == "ok"  # the fallback saved the run
    errors = [e for e in events if e.type == "error"]
    assert len(errors) == 1 and errors[0].data.node == "talk"
    assert "AuthError" in errors[0].data.message and "401" in errors[0].data.message
    # tokens and usage come from the model that answered
    text = "".join(e.data.text for e in events if e.type == "token")
    assert text == "answer from the backup model"
    llm = [e for e in events if e.type == "llm_end"]
    assert [e.data.model for e in llm] == ["backup"]
    assert events[-1].data.totals.llm_calls == 1
    assert events[-1].data.totals.output_tokens > 0


def test_no_fallback_fails_the_run(xray: XRay) -> None:
    import pytest

    primary = FailingModel(replies=["never"], model_name="primary-down")
    with pytest.raises(AuthError):
        xray.wrap(build(primary)).invoke({})
    events = xray.only_run()
    assert events[-1].data.status == "error"
    assert [e.data.node for e in events if e.type == "error"] == ["talk"]  # reported once
