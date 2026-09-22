# Evaluation Report

本文档记录 Ebuy-Agent 的公开评测口径，与简历和面试 PPT 保持一致。

项目评测目标不是只判断“最终回复像不像正确答案”，而是同时检查：

1. Agent 是否调用了正确工具；
2. 是否遵守业务红线；
3. 数据库最终状态是否正确；
4. 最终回答是否有证据支持、是否完成必要回复约束。

---

## 1. Evaluation Setup

公开评测集包含 **50 条 Canonical Cases**，Single-Agent 与 Multi-Agent 两种模式分别执行 **3 Runs**。

覆盖 8 类任务场景：

| Category | Scenario |
|---|---|
| C1 | 基础工具 |
| C2 | 事实忠实 |
| C3 | 业务红线 |
| C4 | 最终状态 |
| C5 | 故障韧性 |
| C6 | 多轮交互 |
| C7 | 流程遵从 |
| MIXED | 组合任务 |

Case 可以声明初始 SQLite 状态、工具约束、业务 Policy、最终状态断言和确定性故障注入。

---

## 2. Core Metrics

公开报告采用 4 个核心 Gate：

| Metric | What it checks |
|---|---|
| **Tool Correctness** | required / forbidden 工具、关键调用顺序和执行路径 |
| **Policy Compliance** | 退款确认、订单状态等业务红线 |
| **Final State Accuracy** | 数据库最终状态是否满足 Case 断言 |
| **Faithfulness** | 最终回答是否由 Tool / State Evidence 支撑，并满足必要回复约束 |

每个 Run 最终按 Gate 通过 / 失败进行判定：

~~~text
Task Success =
Tool Correctness
AND Policy Compliance
AND Final State Accuracy
AND Faithfulness
~~~

> 实现层仍保留更细的 deterministic response contract。公开简历 / PPT 口径将其并入 Faithfulness 展示，以减少指标重复。

---

## 3. Initial Evaluation Snapshot

初版 Eval 暴露出两类问题：

- **Measurement issues**：评测器把部分合法 Agent 行为误判为失败；
- **Agent failures**：Agent 本身存在相对时间编造、无证据政策回答、退款确认等问题。

初版测评结果：

| Metric | Single-Agent | Multi-Agent |
|---|---:|---:|
| Tool Correctness | **79.3%** | **87.3%** |
| Policy Compliance | **66.7%** | **71.4%** |
| Final State Accuracy | **100.0%** | **100.0%** |
| Faithfulness | **85.6%** | **83.3%** |
| **Task Success** | **44.8%** | **51.1%** |
| **pass@3** | **58.6%** | **60.0%** |
| **pass³** | **27.6%** | **40.0%** |

这轮结果的主要价值是定位问题，而不是把初始分数本身作为最终模型能力结论。

---

## 4. Calibration & Agent Hardening

针对初版 Audit 暴露的问题，进行了两类修正。

**Evaluator calibration**

- 必答点从严格字面匹配调整为语义判定；
- 合法工具扩展从固定路径改为边界约束；
- 自由文本工具参数采用分级校验；
- Faithfulness 采用逐点 LLM Judge，并配合人工复核。

**Agent hardening**

- 限制相对时间推断，优先引用工具返回的绝对日期；
- Multi-Agent 增加全局能力兜底；
- 限制无证据政策生成；
- 将真实工具调用记录纳入后续生成上下文；
- 执行退款等写操作前检查用户确认信息。

本节只记录修正方向；公开仓库重点保留最终代码、Case、Trace 与评测实现。

---

## 5. Re-evaluation

在校准后的公开报告口径下：

| Metric | Single-Agent | Multi-Agent |
|---|---:|---:|
| Tool Correctness | **99.3%** | **97.3%** |
| Policy Compliance | **99.3%** | **98.7%** |
| Final State Accuracy | **100.0%** | **100.0%** |
| Faithfulness | **96.7%** | **95.3%** |
| **Task Success** | **95.3%** | **94.0%** |
| **pass@3** | **100.0%** | **100.0%** |
| **pass³** | **88.0%** | **90.0%** |

### Reliability Metrics

~~~text
pass@3
= 一个 Case 的 3 Runs 中至少 1 次成功

pass³
= 一个 Case 的 3 Runs 全部成功
~~~

因此：

- pass@3 = 100% 表示所有 Canonical Case 至少有一次可以完成；
- pass³ = 88% / 90% 表示系统仍存在一定非确定性，稳定性并未完全收敛。

---

## 6. Scenario Breakdown

修正后的场景表现：

| Category | Single-Agent | Multi-Agent |
|---|---:|---:|
| C1 基础工具 | **100%** | **100%** |
| C2 事实忠实 | **89%** | **100%** |
| C3 业务红线 | **90%** | **90%** |
| C4 最终状态 | **93%** | **93%** |
| C5 故障韧性 | **94%** | **89%** |
| C6 多轮交互 | **100%** | **100%** |
| C7 流程遵从 | **100%** | **100%** |
| MIXED 组合任务 | **97%** | **87%** |

从场景拆解看，基础工具、多轮和流程类任务已经较稳定；Multi-Agent 在组合任务与故障恢复场景仍然更容易出现链路级不稳定。

---

## 7. Why Stateful Evaluation

Agent 任务与普通 QA 的区别在于：

> “回答看起来正确”不代表“业务真的做对了”。

例如退款任务至少需要同时验证：

~~~text
用户请求
→ Agent 查询订单
→ 检查退款前置条件
→ 获得用户确认
→ 调用退款工具
→ 数据库状态变化
→ 最终回复与真实执行结果一致
~~~

因此 Eval Runner 为每个 Case 创建独立 SQLite 状态，并通过 Tracer / RunTrace 保存：

- User Turns
- LLM Calls
- Tool Calls
- Tool Results
- Route Events
- Fault Events
- Initial State
- Final State
- Final Response

最终评分从这些结构化证据中产生，而不是只依赖一段模型回答。

---

## 8. Failure Attribution

当 Task Success 失败时，系统可以继续定位到：

~~~text
Task Failure
→ Gate
→ RunTrace
→ Tool / State / Response
→ Root Cause
~~~

典型失败类型包括：

- Tool selection / order error
- Tool argument error
- Policy violation
- Final-state mismatch
- Unsupported / contradicted response
- Runtime / Judge incomplete

这使 Eval 不只是一个 scoreboard，也成为 Agent 调试和迭代闭环的一部分。

---

## 9. Reproduction

校验数据集：

~~~bash
python -m app.scripts.run_eval --validate-only
~~~

Single-Agent：

~~~bash
python -m app.scripts.run_eval \
  --runs 3 \
  --mode single \
  --judge \
  --no-diagnostics
~~~

Multi-Agent：

~~~bash
python -m app.scripts.run_eval \
  --runs 3 \
  --mode multi \
  --judge \
  --no-diagnostics
~~~

Eval 实现位于：

~~~text
app/evaluation/
├── dataset/
├── metrics/
├── runner/
├── evaluator.py
├── faults.py
├── state.py
├── tracer.py
├── trace.py
└── report.py
~~~

Canonical 数据集：

~~~text
app/evaluation/dataset/canonical_cases.json
~~~

---

## 10. Reporting Note

本文档使用的是 **公开简历 / PPT 的统一报告口径**。开发过程中曾存在不同版本的 evaluator、不同聚合方式与历史实验产物；这些内部开发材料不作为公开仓库的最终指标来源。

公开版本重点保留：

- 当前项目代码；
- Canonical Case 数据集；
- Stateful Eval 实现；
- 可复现运行入口；
- 与简历 / PPT 一致的最终报告口径。
