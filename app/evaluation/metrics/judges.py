"""Optional semantic judges. They never compensate for deterministic gate failures."""

from __future__ import annotations

import json

from openai import OpenAI

from app.evaluation.trace import ToolObservation
from app.prompts.evaluation import (
    ANSWER_QUALITY_PROMPT,
    HALLUCINATION_PROMPT,
    PROCESS_SOUNDNESS_PROMPT,
)


FAITHFULNESS_SCORES = {
    "supported": 1.0,
    "unverifiable": 0.5,
    "contradicted": 0.0,
    "unsupported": 0.0,
}

_STATE_KEYS = {
    "orders": "order_id",
    "products": "product_id",
    "refunds": "refund_id",
}


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


def _request_json(client: OpenAI, model: str, prompt: str, attempts: int = 1) -> dict:
    """Call one Judge with a bounded retry for transient transport/parse failures."""

    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_json(response.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - caller chooses fail semantics
            last_error = exc
    assert last_error is not None
    raise last_error


def faithfulness_score_from_verdict(verdict: str | None) -> float:
    return FAITHFULNESS_SCORES.get((verdict or "").strip().lower(), 0.0)


def _state_delta(before: dict, after: dict) -> dict:
    """Keep only changed rows so state evidence is complete without duplicating DB dumps."""

    delta: dict[str, list[dict]] = {}
    for table, key in _STATE_KEYS.items():
        before_rows = {row.get(key): row for row in before.get(table, [])}
        after_rows = {row.get(key): row for row in after.get(table, [])}
        changed = [
            {"id": row_id, "before": before_rows.get(row_id), "after": after_rows.get(row_id)}
            for row_id in sorted(set(before_rows) | set(after_rows), key=str)
            if before_rows.get(row_id) != after_rows.get(row_id)
        ]
        if changed:
            delta[table] = changed
    return delta


def judge_answer_quality(
    client: OpenAI,
    model: str,
    user_input: str | list[str],
    reply: str,
    reference: list[str] | None = None,
    structured_output: dict | None = None,
) -> tuple[float, str]:
    turns = user_input if isinstance(user_input, list) else [user_input]
    prompt = ANSWER_QUALITY_PROMPT.format(
        user_input="\n".join(f"第{i + 1}轮：{turn}" for i, turn in enumerate(turns)),
        reply=reply,
        reference="、".join(reference or []) or "（无）",
    )
    if structured_output is not None:
        prompt += "\n\n【最终结构化输出】\n" + json.dumps(
            structured_output, ensure_ascii=False
        )
    try:
        data = _request_json(client, model, prompt, attempts=2)
        return float(data["score"]), data.get("reason", "")
    except Exception as exc:  # noqa: BLE001 - diagnostics must not abort a Case
        return 0.0, f"质量评分解析失败: {exc}"


def judge_faithfulness(
    client: OpenAI,
    model: str,
    reply: str,
    observations: list[ToolObservation],
) -> tuple[float, str, str]:
    evidence_lines = []
    for item in observations:
        state_delta = _state_delta(item.state_before, item.state_after)
        state_text = (
            f"；状态变化={json.dumps(state_delta, ensure_ascii=False)}"
            if state_delta else ""
        )
        evidence_lines.append(
            f"- [{item.status}] {item.name}({item.arguments}) → {item.result}{state_text}"
        )
    evidence = "\n".join(evidence_lines) or "（未调用工具）"
    prompt = HALLUCINATION_PROMPT.format(reply=reply, observations=evidence)
    try:
        data = _request_json(client, model, prompt, attempts=2)
        verdict = str(data["verdict"]).strip().lower()
        return faithfulness_score_from_verdict(verdict), verdict, data.get("reason", "")
    except Exception as exc:  # noqa: BLE001 - judge failure is an explicit hard verdict
        return 0.0, "parse_failed", f"事实核查解析失败: {exc}"


def judge_process_soundness(
    client: OpenAI, model: str, context: dict
) -> tuple[float, str]:
    turns = "\n".join(
        f"第{i + 1}轮：{turn}" for i, turn in enumerate(context.get("user_turns") or [])
    ) or "（无）"
    steps = "\n".join(
        f"- 第{step.get('turn_index', 0) + 1}轮/第{step.get('step_index', 0) + 1}步 "
        f"[{step.get('status')}] {step.get('name')}（{step.get('description') or ''}） "
        f"参数={step.get('arguments')} 返回={step.get('result')}"
        for step in context.get("tool_steps") or []
    ) or "（未调用工具）"
    prompt = PROCESS_SOUNDNESS_PROMPT.format(
        user_turns=turns,
        tool_steps=steps,
        sop=context.get("sop") or "（无）",
    )
    prompt += "\n\n【本轮可用工具完整 Schema】\n" + json.dumps(
        context.get("tool_schema") or [], ensure_ascii=False
    )
    try:
        data = _request_json(client, model, prompt, attempts=2)
        return float(data["score"]), data.get("reason", "")
    except Exception as exc:  # noqa: BLE001 - diagnostics must not abort a Case
        return 0.0, f"过程评分解析失败: {exc}"
