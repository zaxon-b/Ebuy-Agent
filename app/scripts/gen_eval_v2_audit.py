"""Generate eval_v2 per-case audit. Per failing run state FACTS only:

  A(agent did) = tool trace + reply summary (from traces.jsonl)
  B(rule required) = verbatim excerpt from the agent-visible rules
                    (SYSTEM_PROMPT / SKILL.md / tool contract in registry.py)

No adjudication verdict is asserted in A/B; the reader (or the final
adjudication script) decides whether A violates B.
"""

from __future__ import annotations

import json
from pathlib import Path

MAT = Path("eval_v2/audit_material.json")
ADJ = Path("artifacts/eval/adjusted_scores.json")
SINGLE = Path("artifacts/eval/20260904-104253")
MULTI = Path("artifacts/eval/20260905-024018")
OUT = Path("eval_v2/CASE_AUDIT.md")

WHAT_KEY: dict[tuple[str, int], str] = {}

CAT = {"C1":"工具调用正确性","C2":"回答忠实度","C3":"业务红线","C4":"数据库终态",
       "C5":"故障韧性","C6":"多轮协议","C7":"SOP 获取与遵从","MIXED":"混合综合"}

# verbatim rules the agent can actually see
RULES = {
    "sp1": "SYSTEM_PROMPT『使用原则1』当顾客询问具体订单/商品/物流数据时，必须先调用对应的查询工具，不要凭空编造",
    "sp3": "SYSTEM_PROMPT『使用原则3』订单号查不到→主动调用 list_user_orders 列出订单列表，让顾客确认",
    "sp4": "SYSTEM_PROMPT『使用原则4』根据工具返回的真实数据/检索片段给顾客准确的回答；若检索结果与问题不匹配，可换一种表述再次检索",
    "sp7": "SYSTEM_PROMPT『使用原则7』search_knowledge 检索失败（success=false 或结果为空）→只能告知用户「暂时无法核实，请稍后再试或转人工处理」，不得依据通用知识给出具体政策结论",
    "sp8": "SYSTEM_PROMPT『使用原则8』回复中涉及时间时，只复述工具返回的具体日期/时间，不要使用「今天」「明天」等相对说法",
    "sp-b": "SYSTEM_PROMPT『边界约束』不要编造不确定的信息；不要做出超出权限的承诺",
    "trk-pending": "track-order SKILL『第二步』pending（待发货）→告知用户订单正在处理，尚未发货",
    "trk-ship": "track-order SKILL『第二步→第三步』shipped（已发货）→进入第三步查物流；delivered→告知签收时间地点",
    "trk-step3-head": "track-order SKILL『第三步』调用 query_logistics 获取物流信息（仅已发货/已签收订单）",
    "ret-step4": "process-return SKILL『第四步』与用户确认退款原因（必须，不能跳过），确认后调用 apply_refund",
    "ret-step2": "process-return SKILL『第二步』判断订单状态；refund_processing（退款处理中）→告知已有退款申请正在处理，无需重复申请",
    "prod-reco-3": "product-recommend SKILL『第三步』如果结果不理想，换用同义词或上层品类再搜一次",
    "tool-qlog": "工具契约 query_logistics：仅已发货/posted/delivered 可查；pending 应提示尚未发货，不要调用",
    "tool-refund": "工具契约 apply_refund：敏感操作，必须先确认订单号和退款原因、得到用户明确确认后才能调用",
}

# per (mode, case, run) exact A→B facts. Keys must cover every failing run
# (FLIP / KEEP_FAIL / FILL_ASSUM). A = what agent did (tool trace + tool returns
# + full reply); B = rule verbatim ref. Stored as 4-tuple (a, b, machine, decision).
FACTS: dict[tuple[str, str, int], tuple[str, str, str, str]] = {}

# --- generic auto-fill: A from material (tool path), B by rule pointer ---
# (filled below by reading traces and mapping rules per case class)

# rule pointer per case (which RULES keys apply as the B that failing run may violate)
CASE_RULES: dict[str, list[str]] = {
    "v2_c1_t01": ["sp1", "trk-ship", "trk-step3-head"],
    "v2_c1_t02": ["sp1", "trk-ship", "trk-step3-head"],
    "v2_c1_t03": ["sp1", "trk-ship", "trk-step3-head"],
    "v2_c1_t04": ["sp1", "prod-reco-3"],
    "v2_c1_t05": ["sp1", "sp4", "sp7"],
    "v2_c1_t06": ["sp1", "sp4", "ret-step2"],
    "v2_c1_t07": ["sp1", "sp4"],
    "v2_c2_t08": ["sp1", "prod-reco-3"],
    "v2_c2_t09": ["sp4", "prod-reco-3"],
    "v2_c2_t10": ["sp3"],
    "v2_c2_t11": ["sp7", "sp4"],
    "v2_c2_t12": ["sp1", "trk-ship"],
    "v2_c2_t13": ["sp4", "prod-reco-3"],
    "v2_c3_t15": ["ret-step4", "ret-step2"],
    "v2_c3_t16": ["trk-pending", "tool-qlog"],
    "v2_c3_t17": ["ret-step2", "ret-step4"],
    "v2_c3_t18": ["ret-step2"],
    "v2_c3_t20": ["sp1"],
    "v2_c4_t21": ["ret-step4"],
    "v2_c4_t22": ["ret-step4"],
    "v2_c4_t23": ["trk-pending", "trk-step3-head"],
    "v2_c4_t25": ["sp1"],
    "v2_c5_t26": ["sp4"],
    "v2_c5_t27": ["sp1"],
    "v2_c5_t28": ["sp4", "sp7"],
    "v2_c5_t29": ["sp7", "sp-b", "tool-qlog"],
    "v2_c5_t31": ["sp4", "sp7"],
    "v2_c6_t34": ["trk-ship", "trk-step3-head"],
    "v2_c6_t37": ["sp1", "trk-ship"],
    "v2_c7_t40": ["ret-step4"],
    "v2_m_m2": ["sp1"],
    "v2_m_m3": ["sp1", "sp-b"],
    "v2_m_m5": ["sp4"],
    "v2_m_m6": ["sp4", "sp7"],
    "v2_m_m7": ["trk-pending", "sp1"],
    "v2_m_m8": ["trk-pending", "tool-qlog"],
    "v2_m_m9": ["sp4"],
    "v2_m_m10": ["sp7", "sp-b", "tool-qlog"],
}


def load_trace(mode, cid, run):
    path = SINGLE if mode == "single" else MULTI
    for line in open(path / "traces.jsonl"):
        t = json.loads(line)
        if t["case_id"] == cid and t["run_index"] == run:
            tr = t["trace"]
            tools = []
            for x in tr.get("tool_calls", []):
                tools.append({
                    "name": x.get("name"),
                    "status": x.get("status"),
                    "kwargs": x.get("kwargs"),
                    "result": x.get("result"),
                })
            return tools, (tr.get("reply") or "")
    return [], ""


def fmt_tool_result(res):
    """工具返回可能已是 str（JSON 字符串）也可能是对象，统一转可读文本。"""
    if isinstance(res, str):
        return res
    return json.dumps(res, ensure_ascii=False)


def build_a_part(tools, reply):
    """A = 工具轨迹 + 每个工具返回全文 + 回复全文。让审计者自己对照。"""
    out = []
    for i, t in enumerate(tools, 1):
        head = f"{i}. `{t['name']}` ({t['status']})"
        if t["kwargs"]:
            head += " · 参数 " + json.dumps(t["kwargs"], ensure_ascii=False)
        out.append(head)
        if t["result"]:
            for ln in fmt_tool_result(t["result"]).splitlines():
                out.append("    返回> " + ln)
    out.append(f"回复全文：{(reply or '(空)').strip()}")
    return "\n".join(out)


def build_facts(mask):
    """A = tool trace + reply head (facts). B = rule verbatim list for this case.
    Also capture the machine's raw judgment (tool reasons / judge verdict / scores)."""
    for mode in ("single", "multi"):
        path = SINGLE if mode == "single" else MULTI
        raw_cases = {}
        for line in open(path / "cases.jsonl"):
            c = json.loads(line)
            raw_cases[(c["case_id"], c["run_index"])] = c
        for a in json.load(open(ADJ))["audit"][mode]:
            if a["decision"] not in ("FLIP", "KEEP_FAIL", "FILL_ASSUM"):
                continue
            cid, run = a["case"], a["run"]
            WHAT_KEY[(mode, cid, run)] = a.get("what") or a.get("why") or ""
            tools, reply = load_trace(mode, cid, run)
            a_part = build_a_part(tools, reply)
            b_refs = CASE_RULES.get(cid, ["sp1"])
            b_part = "；".join(RULES[k] for k in b_refs)
            # machine raw judgment for this run
            rc = raw_cases.get((cid, run), {})
            core = rc.get("core", {})
            judge = (rc.get("judge_reasons") or {}).get("faithfulness") or ""
            verdict = core.get("faithfulness_verdict")
            machine_part = (
                f"machine tool_correctness={core.get('tool_correctness')} "
                f"tool_reasons={rc.get('tool_details', {}).get('reasons')} "
                f"arg_acc={rc.get('tool_details', {}).get('argument_accuracy')} "
                f"order_pass={rc.get('tool_details', {}).get('order_pass')} "
                f"faith={verdict} judge: {judge[:150]}"
            )
            decision = a["decision"]
            FACTS[(mode, cid, run)] = (a_part, b_part, machine_part, decision)


def main():
    mat = json.load(open(MAT))
    mask_ = {(m, a["case"], a["run"]): a["decision"]
             for m in ("single", "multi") for a in json.load(open(ADJ))["audit"][m]}
    build_facts(mask_)

    lines = [
        "# Eval V2 · 逐 Case Audit",
        "",
        "> 颜色：🟢 全程通过（无失败）· 🟡 有误判但修正后通过 · 🔴 修正后仍保留失败。",
        "> 每条失败轮给「A（Agent 实际行为：工具轨迹 + 每个工具返回全文 + 回复全文）」与「B（给 Agent 的规则原文引用）」。\n"
        "> 读 A 时可直接对照：回复里每个事实是否能从某个工具返回里找到依据；以此区分「reply 出格」还是「评判器误罚」。",
        "> 判定是否违反由审计者（人）按 A∉B 自行判断——此处只列事实，不下结论；最终裁决见 `artifacts/eval/adjusted_scores.json`。",
        "> 规则原文出处：SYSTEM_PROMPT（app/prompts/customer_service.py）· SKILL.md（app/agent/skills/definitions/）· 工具契约（app/agent/tools/registry.py）。",
        "",
    ]
    for cid in sorted(mat, key=lambda x: (mat[x]["category"], x)):
        c = mat[cid]
        decs = [mask_.get((m, cid, r["run"])) or "PASS"
                for m in ("single", "multi") for r in c["runs"][m]]
        dot = "🔴" if "KEEP_FAIL" in decs else ("🟡" if any(d in ("FLIP", "FILL_ASSUM") for d in decs) else "🟢")
        lines.append(f"## {cid} {dot} [{c['category']} {CAT[c['category']]}] — {c['desc']}")
        lines += ["", f"- **难度** {c['level']} · **对话** {c['dialogue']}"]
        lines.append(f"- **期望路径** `{'→'.join(t['tool'] for p in c['paths'] for t in p)}`")
        extras = []
        if c["forbidden"]: extras.append(f"forbidden={c['forbidden']}")
        if c["policy"]: extras.append(f"policy={c['policy']}")
        if c["extendable"]: extras.append(f"extendable={c['extendable']}")
        if c["faults"]: extras.append(f"faults={json.dumps(c['faults'], ensure_ascii=False)}")
        lines.append(f"- **约束** {' · '.join(extras) if extras else '—'}")
        for m in ("single", "multi"):
            runs = c["runs"][m]
            if not runs:
                continue
            passed_n = sum(r["passed"] for r in runs)
            lines.append(f"- **{m}** 通过 `{passed_n}/3`")
            for r in runs:
                d = mask_.get((m, cid, r["run"]))
                mark = "✅" if r["passed"] else "❌"
                if d == "FLIP": tag = "修正·Eval/Judge误罚→通过"
                elif d == "FILL_ASSUM": tag = "修正·run3假设→通过(★未实测)"
                elif d == "KEEP_FAIL": tag = "真缺陷·保留失败"
                else: tag = "通过"
                lines.append(f"    - `run{r['run']}` {mark} — **{tag}**" + (f"  fails={r['fails']}" if r['fails'] else ""))
                key = (m, cid, r["run"])
                if key in FACTS and d != "PASS":
                    a_part, b_part, machine_part, _ = FACTS[key]
                    lines.append("      - **A（Agent 实际）**：")
                    for ln in a_part.split("\n"):
                        lines.append(f"        {ln}")
                    lines.append(f"      - **B（给 Agent 的规则）**：{b_part}")
                    lines.append(f"      - **机器判据原文**：{machine_part}")
                    # adjudication reason from the final decision table
                    why = WHAT_KEY.get(key, "")
                    lines.append(f"      - **裁决**：{d} — {why}")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written", OUT, "lines:", len(lines))


if __name__ == "__main__":
    main()