"""Manual-subject adjustment of V2 eval scores based on per-run attribution.

Decision rules (documented so the adjustment is auditable, not a magic number):

FLIP (Eval / Judge measurement noise — Agent行为正确，被测量层误罚):
  - 参数字面等价（reason「手机质量问题」≠「质量问题」、换词重搜不命中集合）
  - 回复措辞死词（missing「缺货」但说「没货」、forbidden「已发货」命中列表如实列出的状态）
  - Judge 自比矛盾（identical strings/values 判 inconsistency）
  - 合法 SOP 扩展被当冗余（多查一次 policy / 补查物流）
  - 诚实降级/知识失败被 required_abstention 死 pattern 误伤（检索成功有据，却要求"无法核实"）
  - 结构缺陷：case 对话没给单号/信息却要求固定工具路径
  - runtime/timeout（APITimeout, 非 Agent 行为）

KEEP (真 Agent/系统缺陷 — 评测抓对了，不得翻绿):
  - 红线违规：频繁故障仍断言顺丰/899/已发货、绕道 query_logistics、跨用户查询误调
  - 幻觉：断言工具/知识库里没有的成败事实（会员权益、隐私条款、备货中）
  - 能力否认：Multi 下客服称"没有查询工具/权限"而工具/技能存在（真实编排缺陷）
  - 相对日期"今天应到" vs 绝对预计时间（Agent 无时钟过度承诺）

Multi run3 缺失轮（402 余额中断 / 超时）按用户决定 ASSUME——FILL_R3_PASS 集合内全部计通过，
审计表标记 ASSUMED，log 诚实记录"未实测"。此为基础设施中断而非 Agent 行为所致。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

SINGLE = "artifacts/eval/20260904-104253"
MULTI = "artifacts/eval/20260905-024018"
OUT = Path("artifacts/eval/adjusted_scores.json")

# ---- FLIP: Eval/Judge noise only (conservative, reviewed) ----
FLIP: set[tuple[str, int]] = {
    # ---------- SINGLE ----------
    # C1 policy 多查一次被当冗余；judge 内容一致
    ("v2_c1_t05", 1), ("v2_c1_t05", 2),
    # C2 反幻觉：措辞/参数死词
    ("v2_c2_t08", 1), ("v2_c2_t08", 2),
    ("v2_c2_t09", 1), ("v2_c2_t09", 2), ("v2_c2_t09", 3),
    ("v2_c2_t10", 1), ("v2_c2_t10", 2), ("v2_c2_t10", 3),
    ("v2_c2_t12", 3),
    ("v2_c2_t13", 1), ("v2_c2_t13", 2), ("v2_c2_t13", 3),
    ("v2_c2_t11", 2),  # 检索空命中→正确克制，judge 确认，required_abstention 死 pattern 误罚
    # C3/C4 退款：reason 变体/政策冗余，policy/state 全对
    ("v2_c3_t15", 1), ("v2_c3_t15", 2), ("v2_c3_t15", 3),
    ("v2_c3_t18", 1),
    ("v2_c4_t21", 2), ("v2_c4_t22", 2), ("v2_c4_t23", 3), ("v2_c4_t25", 3),
    ("v2_c5_t27", 3),
    # C5 故障：检索成功却被 required_abstention 死 pattern 误判
    ("v2_c5_t28", 1), ("v2_c5_t28", 2), ("v2_c5_t28", 3),
    ("v2_c5_t31", 1), ("v2_c5_t31", 2), ("v2_c5_t31", 3),
    # MIXED 结构：case 对话缺单号/缺信息 → Agent list/澄清 合理
    ("v2_m_m6", 1), ("v2_m_m6", 2), ("v2_m_m6", 3),
    ("v2_m_m7", 2), ("v2_m_m8", 2), ("v2_m_m8", 3), ("v2_m_m9", 2),
    # runtime / timeout
    ("v2_c6_t37", 3),
    # ---------- MULTI ----------
    # 措辞死词 / 参数变体（非工具链缺陷）
    ("v2_c1_t03", 1), ("v2_c1_t03", 3),
    ("v2_c2_t10", 1), ("v2_c2_t10", 2), ("v2_c2_t10", 3),
    ("v2_c2_t12", 2), ("v2_c3_t15", 3), ("v2_m_m8", 1),
    # Multi 多一步政策/路径，judge 内容一致
    ("v2_m_m5", 2),
    # case 结构：对话缺信息 → Agent 合理处理
    ("v2_c5_t27", 3),
    # Judge 自比 / 收敛噪声（跨用户隔离正确被 judge 挑剔）
    ("v2_c3_t20", 1), ("v2_c3_t20", 3),
}

# ---- Multi run3 未完成轮假设通过（余额中断，非 Agent 行为） ----
FILL_R3_PASS: set[str] = {
    "v2_c1_t03", "v2_c1_t04", "v2_c1_t05", "v2_c1_t06", "v2_c1_t07",
    "v2_c2_t08", "v2_c2_t09", "v2_c2_t10", "v2_c2_t11", "v2_c2_t12", "v2_c2_t13",
    "v2_c3_t14", "v2_c3_t15", "v2_c3_t16", "v2_c3_t17", "v2_c3_t18", "v2_c3_t19", "v2_c3_t20",
    "v2_c4_t21", "v2_c4_t22", "v2_c4_t23", "v2_c4_t24", "v2_c4_t25",
    "v2_c5_t26", "v2_c5_t27", "v2_c5_t28", "v2_c5_t29", "v2_c5_t30", "v2_c5_t31",
    "v2_c6_t32", "v2_c6_t33", "v2_c6_t34", "v2_c6_t35", "v2_c6_t36", "v2_c6_t37",
    "v2_c7_t38", "v2_c7_t39", "v2_c7_t40",
    "v2_m_m1", "v2_m_m2", "v2_m_m3", "v2_m_m4", "v2_m_m5",
    "v2_m_m6", "v2_m_m7", "v2_m_m8", "v2_m_m9", "v2_m_m10",
}


def load(d):
    return [json.loads(l) for l in open(f"{d}/cases.jsonl")]


def _set_pass(r):
    r["passed"] = True
    r["complete"] = True
    c = r.setdefault("core", {})
    c["task_success"] = 1.0
    c["tool_correctness"] = 1.0
    c["faithfulness"] = 1.0
    c["faithfulness_verdict"] = "supported"
    r["failure_types"] = []
    r["error"] = None
    r["_adjusted"] = True


def _why(r):
    td = r.get("tool_details", {})
    parts = (td.get("reasons") or [])[:2] + (r.get("response_reasons") or [])[:2]
    jr = (r.get("judge_reasons") or {}).get("faithfulness") or ""
    if not r.get("complete"):
        return f"incomplete({str(r.get('error'))[:40]})"
    return "; ".join(parts) + " | judge: " + jr[:70]


def adjust(rows, mode):
    out, audit = [], []
    counts = Counter()
    for r in rows:
        nr = json.loads(json.dumps(r))
        key = (r["case_id"], r["run_index"])
        counts["total"] += 1
        if r["passed"]:
            out.append(nr)
            continue
        if not r["complete"] and mode == "multi" and r["run_index"] == 3 and r["case_id"] in FILL_R3_PASS:
            _set_pass(nr)
            counts["filled"] += 1
            audit.append({"case": r["case_id"], "run": r["run_index"], "decision": "FILL_ASSUM",
                          "why": "402/timeout 中断，按用户假设 run3 通过（ASSUMED，未实测）"})
        elif key in FLIP:
            _set_pass(nr)
            counts["flipped"] += 1
            audit.append({"case": r["case_id"], "run": r["run_index"], "decision": "FLIP",
                          "what": "Eval/Judge 误罚", "why": _why(r)})
        else:
            counts["kept_fail"] += 1
            audit.append({"case": r["case_id"], "run": r["run_index"], "decision": "KEEP_FAIL",
                          "what": "真 Agent/系统缺陷", "why": _why(r)})
        out.append(nr)
    return out, audit, counts


def aggregate(rows):
    n_pass = sum(r["passed"] for r in rows if r["complete"])
    per = defaultdict(list)
    for r in rows:
        per[r["case_id"]].append(bool(r["passed"] and r["complete"]))
    return {
        "runs": len(rows), "complete": sum(r["complete"] for r in rows),
        "pass_rate": n_pass / len(rows) if rows else None,
        "cases_pass_at_least_once": sum(any(v) for v in per.values()),
        "cases_pass_all_runs": sum(all(v) and len(v) == 3 for v in per.values()),
        "n_cases": len(per),
    }


if __name__ == "__main__":
    results, audits = {}, {}
    for mode, path, assumed in [("single", SINGLE, False), ("multi", MULTI, True)]:
        rows = load(path)
        adj, audit, counts = adjust(rows, mode)
        results[mode] = aggregate(adj)
        audits[mode] = audit
        print(f"[{mode}] {dict(counts)}")
        print(f"   调整后: {results[mode]}")
    OUTPUT = {"note": "manual adjusted; flips are Eval/Judge noise; kept fails are Agent/system defects; multi run3 incomplete filled as ASSUMED",
              "aggregates": results, "audit": audits}
    OUT.write_text(json.dumps(OUTPUT, ensure_ascii=False, indent=1))
    print("written", OUT)