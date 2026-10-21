from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.agent import AgentRuntime, reset_session


client = TestClient(app)


def _runtime(monkeypatch) -> AgentRuntime:
    monkeypatch.setenv("TIANZHEN_LLM_DISABLE", "1")
    return AgentRuntime()


def test_fallback_full_flow_produces_validation_and_windows(monkeypatch):
    runtime = _runtime(monkeypatch)
    result = runtime.run(
        "番茄叶子背面长白毛，茎上有黑斑，5天后采收，能用什么药？",
        "番茄",
        harvest_in_days=5,
    )

    assert result.mode == "fallback"
    assert result.session_id
    assert result.artifacts["validation"]["per_item"]
    assert result.artifacts["spray_windows"]
    assert result.to_dict()["ready_for_field_use"] is False
    tools = [step["tool"] for step in result.steps]
    assert "search_disease" in tools
    assert "get_candidate_records" in tools
    assert "validate_prescription" in tools
    assert "get_spray_window" in tools
    assert "不签发正式田间处方" in result.reply


def test_fallback_asks_for_clarification_on_negative_symptoms(monkeypatch):
    runtime = _runtime(monkeypatch)
    result = runtime.run("没有白毛，也不是晚疫病，还需要看什么？", "番茄")

    assert result.mode == "fallback"
    assert result.clarification
    assert "validation" not in result.artifacts
    assert any(step["tool"] == "ask_user" for step in result.steps)


def test_validation_blocks_identity_mismatch(monkeypatch):
    runtime = _runtime(monkeypatch)
    records = runtime.kb.candidates_for("番茄", "晚疫病")
    assert len(records) >= 2
    first, second = records[0], records[1]

    payload = runtime._tool_validate(
        {
            "crop": "番茄",
            "disease": "晚疫病",
            "items": [
                {
                    "pesticide_name": second.pesticide_name,
                    "source_record_id": first.record_id,
                    "dosage_value": second.dosage_min,
                    "dosage_unit": second.dosage_unit,
                    "safety_interval_days": second.safety_interval_days,
                }
            ],
            "harvest_in_days": 30,
        }
    )

    assert payload["decision"] == "blocked"
    reasons = [
        item["message"]
        for item in payload["per_item"][0]["blocking"]
        + payload["per_item"][0]["review"]
    ]
    assert any("身份" in reason or "不一致" in reason for reason in reasons)


def test_llm_loop_executes_tool_calls_and_returns_final_answer(monkeypatch):
    runtime = _runtime(monkeypatch)

    class FakeLLM:
        available = True
        disabled = False

        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_disease",
                                            "arguments": json.dumps(
                                                {"symptoms": "叶子背面长白毛", "crop": "番茄"},
                                                ensure_ascii=False,
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "已完成检索，请补充采收时间后再做规则校验。",
                        }
                    }
                ]
            }

    runtime.llm = FakeLLM()
    result = runtime.run("叶子背面长白毛", "番茄")

    assert result.mode == "llm"
    assert result.steps
    assert result.steps[0]["tool"] == "search_disease"
    assert result.artifacts["disease_matches"]
    assert "已完成检索" in result.reply


def test_followup_reuses_last_validation(monkeypatch):
    runtime = _runtime(monkeypatch)
    first = runtime.run(
        "番茄叶子背面长白毛，茎上有黑斑，5天后采收，能用什么药？",
        "番茄",
        harvest_in_days=5,
    )
    second = runtime.run("为什么这些条目需要复核？", "番茄", session_id=first.session_id)

    assert second.mode == "fallback"
    assert "规则检查" in second.reply or "待核验" in second.reply
    assert second.artifacts.get("validation")


def test_agent_chat_api_and_session(monkeypatch):
    monkeypatch.setenv("TIANZHEN_LLM_DISABLE", "1")
    response = client.post(
        "/api/agent/chat",
        json={
            "crop": "番茄",
            "message": "番茄叶子背面长白毛，茎上有黑斑，5天后采收，能用什么药？",
            "harvest_in_days": 5,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "fallback"
    assert payload["session_id"]
    assert payload["ready_for_field_use"] is False
    assert payload["artifacts"]["validation"]["per_item"]

    session_id = payload["session_id"]
    followup = client.post(
        "/api/agent/chat",
        json={
            "crop": "番茄",
            "message": "为什么这些条目需要复核？",
            "session_id": session_id,
            "harvest_in_days": 5,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["session_id"] == session_id
    reset_session(session_id)


def test_agent_chat_rejects_empty_input():
    response = client.post("/api/agent/chat", json={"crop": "番茄", "message": "   "})
    assert response.status_code == 400


def test_agent_chat_rejects_unsupported_crop():
    response = client.post(
        "/api/agent/chat",
        json={"crop": "玉米", "message": "叶子有病斑"},
    )
    assert response.status_code == 400


def test_agent_page_is_served():
    response = client.get("/agent")
    assert response.status_code == 200
    assert "智能体对话" in response.text
    assert "/api/agent/chat" in response.text
