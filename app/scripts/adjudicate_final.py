"""Eval V2 final per-run adjudication against the AGENT-VISIBLE rules (v2).

The adjudication standard is: does the agent's behavior comply with the rules the
agent can actually see — SYSTEM_PROMPT (app/prompts/customer_service.py),
SKILL.md (app/agent/skills/definitions/*/SKILL.md), tool contract (registry.py)?

A run is FLIPPED (marked PASS despite raw fail) ONLY when:
  - the raw failure is a measurement defect (dead-string param, wording,
    Judge self-compare, abort-pattern on successful retrieval), AND
  - the agent's actual behavior complies with the agent-visible rules.

A run is KEPT FAIL when the agent broke an agent-visible rule (repeated refund,
relative-date "今天" without clock, capability denial, missing required call,
off-SOP path) — those are real defects, not noise.

Every adjudicated FLIP carries (A=agent did, B=rule required) so the audit can
state: "agent output X; rule requires Y".
"""

from __future__ import annotations

import json
from pathlib import Path

ADJ = Path("artifacts/eval/adjusted_scores.json")
OUT = Path("artifacts/eval/adjusted_scores.json")

# (mode, case, run) -> (verdict, rule_evidence)
#   verdict: "flip" | "keep"
#   rule_evidence: short "A→B" used in audit
ADJUDICATE: dict[tuple[str, str, int], tuple[str, str]] = {
    # ================= SINGLE =================
    # ---- C1 ----
    ("single", "v2_c1_t05", 1): ("flip", "search×1 命中,tool 有据; judge 把'黄金取件免费/钻石全免'概括判 unsupported,A=复述工具,B=SYSTEM_PROMPT 只复述已检索事实(第1条)→A符合"),
    ("single", "v2_c1_t05", 2): ("flip", "search×2(successful) tool 有据; judge 确认有据; A=换词再搜,B=SYSTEM_PROMPT 第4条'结果不理想可换表述再次检索'→A符合"),
    # ---- C2 ----
    ("single", "v2_c2_t08", 1): ("flip", "query_product×1 命中缺货(库存0), A=如实说没货,B=product-recommend 第6点'库存为0明确告知缺货'(语义达成,缺字面'缺货')→测量措辞死词"),
    ("single", "v2_c2_t08", 2): ("keep", "A=reply 仅'先查看偏好', 未回答用户有无货,B=必须回答缺货→A未完成任务,真缺陷"),
    ("single", "v2_c2_t09", 1): ("flip", "query_product×3 全 count=0, A=换词重搜如实查无,B=product-recommend 第3步'换同义词再搜一次'(合法)→Eval 参数集合没含变体=测量"),
    ("single", "v2_c2_t09", 3): ("flip", "同 r1: 换词重搜如实查无→case keyword 集合太窄=测量"),
    ("single", "v2_c2_t10", 1): ("flip", "query_order(err)+list(6单), A=单号查不到列列表,B=SYSTEM_PROMPT 第3条(单号查不到→列出)→A符合; 仅 forbidden'已发货'命中列表如实状态=measurement"),
    ("single", "v2_c2_t10", 2): ("flip", "同 r1"),
    ("single", "v2_c2_t10", 3): ("flip", "同 r1"),
    ("single", "v2_c2_t11", 2): ("flip", "空命中→Agent 克制(A),B=SYSTEM_PROMPT 第7条'只能暂时无法核实'+第4条允许重试; 多次重试仍空→克制正确,仅 extra=测量"),
    ("single", "v2_c2_t12", 3): ("flip", "order+logistics 回复含已发货信息,缺字面'已发货'; A=语义到位,B=must_include 字面→措辞死词"),
    ("single", "v2_c2_t13", 1): ("flip", "query_product×4 如实查无, A=换词重搜,B=product-recommend 换词合法→case 期望唯一集合=measurement"),
    ("single", "v2_c2_t13", 2): ("flip", "同 r1"),
    ("single", "v2_c2_t13", 3): ("flip", "同 r1"),
    # ---- C3/C4 ----
    ("single", "v2_c3_t15", 1): ("flip", "order+search+search+apply_refund 成功,reason='手机质量问题'; A=语义等价,B=apply_refund(description 例举'质量问题'非穷举)+确认门禁过→仅 reason 字面=measurement"),
    ("single", "v2_c3_t15", 2): ("flip", "同 r1(reason 变体)"),
    ("single", "v2_c3_t15", 3): ("flip", "同 r1"),
    ("single", "v2_c3_t18", 1): ("flip", "order 返回 refunded,reply 如实说已退款; judge'订单号不一致'为等价自比(A=ORD-20240105-006,B=工具亦同)→judge 误判"),
    ("single", "v2_c3_t20", 1): ("keep", "A=在 query_order 失败/确认前先调用 forbidden query_logistics，再 list；B=跨用户/查不到订单时先 query_order，失败后只列本人订单，不查物流→工具路径和 forbidden_tools 均是真缺陷"),
    ("single", "v2_c4_t21", 2): ("keep", "A=apply_refund×2(第1次 error 第2次 success),B=process-return 第四步'确认后才能调用'→确认前调用即违规,trace 显示两次调用=真缺陷"),
    ("single", "v2_c4_t22", 2): ("keep", "同 t21 r2: apply_refund×2→重复触发=真缺陷"),
    ("single", "v2_c4_t23", 3): ("keep", "A=只复述订单并说要继续查会员信息，没有回答已发货订单的拒退路径；B=process-return/track-order 要报告 shipped 状态并给拒收或签收后退货路径，reply_contract 要求签收→最终回答不完整，真缺陷"),
    ("single", "v2_c4_t25", 3): ("flip", "cancelled 回复缺字面'取消'; A=如实说已取消,judge 确认有据→措辞死词"),
    # ---- C5 ----
    ("single", "v2_c5_t27", 3): ("flip", "query_product(err→ok)回复 1799/89 齐全; 缺字面'1799'(¥1,799 标记); judge 说有据→措辞/格式"),
    ("single", "v2_c5_t28", 1): ("flip", "search(err→ok) 成功拿到政策,A=重试成功后给出,B=SYSTEM_PROMPT 第4条允许重试; case 误设 required_abstention→检索成功不需克制=measurement"),
    ("single", "v2_c5_t28", 2): ("flip", "同 r1"),
    ("single", "v2_c5_t28", 3): ("flip", "同 r1"),
    ("single", "v2_c5_t31", 2): ("flip", "search×4 有真实命中,A=引用会员权益,B=工具数据有据,judge 确认; 仅 abstention 死 pattern+多次检索→measurement"),
    ("single", "v2_c5_t31", 3): ("keep", "A=检索已有结果后仍只回复'我再查一下您的会员等级'，没有回答会员退货权益，也没有明确暂时无法核实；B=检索成功后应基于证据答复，或在失败时明确 abstain→最终回复未完成，真缺陷"),
    # ---- runtime ----
    ("single", "v2_c6_t37", 3): ("flip", "APITimeout=infra,非 Agent"),
    # ---- MIXED ----
    ("single", "v2_m_m6", 1): ("flip", "order+search×2,A=查订单并重试政策,B=第4条允许重试; reply 严谨克制→measurement"),
    ("single", "v2_m_m6", 2): ("flip", "同 r1"),
    ("single", "v2_m_m6", 3): ("flip", "同 r1"),
    ("single", "v2_m_m7", 2): ("keep", "A=reply 仅'先了解账户情况'未回答拒退/B=应明确拒退含'签收'→未完成任务,真缺陷"),
    ("single", "v2_m_m8", 1): ("flip", "FSM list 直接答待发货(等价路径); A=用 list 拿到 order 信息,reply 正确,B=FSM 期望 list→order(可辩护简写)→路径测量"),
    ("single", "v2_m_m8", 2): ("flip", "list→order 回复待发货; 缺字面'未发货'(待发货=B,Pending 状态)+路径正确→措辞"),
    ("single", "v2_m_m8", 3): ("flip", "list→order 回复待发货; 缺'未发货'字面→措辞"),
    ("single", "v2_m_m9", 2): ("keep", "load_skill×2+多个 product 发散,A=工具轨迹发散(多余),B=需收敛→真冗余规划"),
    # ================= MULTI =================
    ("multi", "v2_c1_t03", 1): ("flip", "order+logistics 完整; judge 以'工具未明确黑色(仅SKU含BK)'判无依据, A=SKU含BK即黑色语义,B=工具 spec 已含颜色→judge 过度(A 合理推断)"),
    ("multi", "v2_c1_t03", 3): ("flip", "同 r1: SKU BK 含黑色被 judge 挑剔→measurement"),
    ("multi", "v2_c1_t05", 2): ("flip", "同 single: 换词重搜成功有据→measurement"),
    ("multi", "v2_c2_t08", 1): ("keep", "Multi 子Agent reply'无法查询实时库存'→能力否认,B=tool 有 query_product→真编排缺陷"),
    ("multi", "v2_c2_t08", 2): ("keep", "同 r1: 能力否认→真缺陷"),
    ("multi", "v2_c2_t09", 1): ("keep", "Multi 子Agent'没有商品库存查询工具'→能力否认→真缺陷"),
    ("multi", "v2_c2_t09", 2): ("keep", "同 r1"),
    ("multi", "v2_c2_t09", 3): ("keep", "同 r1"),
    ("multi", "v2_c2_t10", 1): ("flip", "同 single: 单号查不到列列表→符合第3条; 仅 forbidden'已发货'命中列表=measurement"),
    ("multi", "v2_c2_t10", 2): ("flip", "同 r1"),
    ("multi", "v2_c2_t10", 3): ("flip", "同 r1"),
    ("multi", "v2_c2_t12", 2): ("keep", "A=reply「很快就能送到啦～预计明天（1月19日）送达」用相对时效词；B=规则8只复述工具绝对日期 2024-01-19，不得用很快/明天等相对说法→真缺陷(用户口径:只禁事件时间)"),
    ("multi", "v2_c2_t13", 1): ("keep", "能力否认'无商品在售功能'→真缺陷"),
    ("multi", "v2_c2_t13", 2): ("keep", "同 r1"),
    ("multi", "v2_c2_t13", 3): ("keep", "同 r1"),
    ("multi", "v2_c3_t15", 3): ("flip", "reason 变体→measurement(同 single)"),
    ("multi", "v2_c3_t20", 3): ("flip", "跨用户隔离正确(单不存在判定,失败调用作'未找到')→Agent 无错,judge 挑剔"),
    ("multi", "v2_c4_t23", 3): ("keep", "A=reply 把物流事件时间'2024-01-18 08:30'复述为'今天 08:30 已到达上海浦东区'；B=规则8只复述工具返回的绝对时间，不得用相对时间→真缺陷(用户口径:只禁事件时间)"),
    ("multi", "v2_c4_t25", 3): ("keep", "A=把 query_order 未返回的颜色'白色'写进回复；B=SYSTEM_PROMPT 只复述工具事实、不得编造→颜色无证据，faithfulness 真缺陷（退款措辞可单独从严审，不改变颜色错误）"),
    ("multi", "v2_c5_t27", 3): ("keep", "能力否认'无法查商品价格库存'→真缺陷"),
    ("multi", "v2_c5_t28", 1): ("flip", "瞬时失败→重试成功给有据政策; required_abstention 与成功矛盾→measurement"),
    ("multi", "v2_m_m5", 2): ("keep", "A=首次 query_order 返回 504 后先调用 query_logistics，随后才重试 query_order；B=SYSTEM_PROMPT 第9条要求 504/5xx 先用相同参数重试一次→重试顺序违反韧性纪律，真缺陷"),
    ("multi", "v2_m_m6", 2): ("flip", "order+search×3(重试), reply 克制,B=第4/7条允许→measurement"),
    ("multi", "v2_m_m8", 1): ("flip", "list→order 待发货,缺'未发货'字面→措辞"),
    ("multi", "v2_m_m8", 2): ("flip", "runtime timeout→infra(非 Agent 行为),按基础设施中断处理"),
    ("multi", "v2_m_m9", 2): ("flip", "runtime timeout→infra(非 Agent 行为),按基础设施中断处理"),
    # ---- 补全 multi / single KEEP（真缺陷，A→B） ----
    ("multi", "v2_c1_t04", 1): ("keep", "子Agent'无法查商品价格库存'而查工具存在→能力否认,真缺陷"),
    ("multi", "v2_c1_t04", 2): ("keep", "同 r1"),
    ("multi", "v2_c1_t04", 3): ("keep", "同 r1"),
    ("multi", "v2_c1_t07", 1): ("keep", "reply'今天应到'vs estimated_delivery=01-19→相对日期过度承诺,真缺陷"),
    ("multi", "v2_c1_t07", 2): ("keep", "同 r1: 称无库存查询能力+今天应到→缺陷"),
    ("multi", "v2_c1_t07", 3): ("keep", "同 r1: 今天应到/能力否认"),
    ("multi", "v2_c5_t29", 1): ("keep", "持续故障→reply断言顺丰/899/已发货+绕查 logistics→红线违规,真缺陷"),
    ("multi", "v2_c5_t29", 2): ("keep", "同 r1"),
    ("multi", "v2_m_m2", 1): ("keep", "强投诉(开箱损坏): 未转人工且承诺'一定给您处理到位/我马上帮您申请退款'——越界承诺; '黑色'=sku-BK解码、'质量问题'=用户自述(原措辞不准,已重审修正)"),
    ("multi", "v2_m_m2", 2): ("keep", "同 r1: 强投诉未转人工+承诺'马上帮您申请退款/换货'"),
    ("multi", "v2_m_m3", 1): ("flip", "用户明确要求查他人订单；query_order 按 user_id 隔离且返回查不到，list_user_orders 只返回本人。A=解释只能查本人并列出本人订单；B=tool/data contract 要求尊重账户隔离→Judge 忽略隐私边界，误判无依据"),
    ("multi", "v2_m_m3", 2): ("flip", "同 r1：A=说明无法查询他人订单并列出本人订单；B=SQLiteStore/tool contract 按 user_id 过滤→隐私边界是数据层可验证规则，Judge 过严"),
    ("multi", "v2_m_m9", 1): ("keep", "能力否认(重审修正): tools 无 query_product 调用，reply 称'暂时查不到商品在售库存'；且 reply 含'今天正在派送中/预计明天送达'相对日期→真缺陷"),
    ("multi", "v2_m_m10", 1): ("keep", "强投诉+故障: reply 断言顺丰/已发货(绕知)→红线,真缺陷"),
    ("multi", "v2_m_m10", 2): ("keep", "同 r1"),
    ("multi", "v2_c3_t16", 2): ("flip", "pending 工具状态的中文含义就是'待发货/订单正在处理'；single r1、multi r1/r3 同语义均被接受。A=回复'商家还在备货处理中'；B=track-order pending 分支要求告知订单正在处理、尚未发货→Judge 把状态翻译判成幻觉"),
    ("multi", "v2_c4_t25", 1): ("flip", "取消状态由 query_order 明确返回，case 又明确 forbidden apply_refund；A=说明已取消、不能再次申请退款；B=工具/状态约束禁止对 cancelled 重复退款→Judge 要求额外退款凭证，过严且跨轮不一致"),
    ("multi", "v2_c4_t25", 2): ("keep", "A=仅凭 cancelled 状态断言已支付款项'应该已经按原路退回'并给出 1-3 个工作日；B=SYSTEM_PROMPT 只复述工具/检索事实，该轮未检索退款政策→退款到账结论无证据，Judge 此处判无依据是正确的"),
    ("multi", "v2_c6_t32", 2): ("keep", "重审修正: reply 有顺丰(非漏报)但含'预计明天就能送到'(相对事件时间,违反规则8); 且 query_logistics 重复调2次(extra get)→真缺陷"),
    ("multi", "v2_c6_t34", 1): ("keep", "reply'今天(1/18)应到'vs estimated 01-19→相对日期,真缺陷"),
    ("multi", "v2_c1_t05", 3): ("flip", "A=search×2均 success 且完整引用政策；B=SYSTEM_PROMPT 允许结果不理想时换表述再次检索→Agent 合规，机器 exact path 误罚 extra call"),
    ("multi", "v2_c1_t06", 3): ("keep", "A=reply 商品写'（黑色）'且把退货条件扩写成'未激活、未使用、无损坏'；B=SYSTEM_PROMPT 第4条只复述工具返回数据：订单 items 名字无字面颜色(仅 sku -BK)、政策原文'未洗涤、未使用、未损坏'并未要求手机须未激活→reply 捏造'未激活'退货条件，真缺陷(用户裁决)"),
    ("multi", "v2_c5_t27", 1): ("keep", "能力否认'无法查价库'→真缺陷"),
    ("multi", "v2_c5_t27", 2): ("keep", "同 r1"),
    ("multi", "v2_c2_t08", 3): ("keep", "能力否认→真缺陷"),
    # single kept (除 ADJUDICATE 已列的)
    ("single", "v2_c2_t08", 3): ("keep", "A=reply 空/无正文,judge'无法对照'→空回复,真缺陷"),
    ("single", "v2_c7_t40", 2): ("flip", "A=说明无法用只有 order_id/reason 的退款工具只退合并订单中的单件，并转人工；B=process-return 明示复杂部分/多商品退款应转人工，tool contract 也无 item 参数→Agent 合规，结构化 requires_human/Judge 误判"),
    ("single", "v2_c7_t40", 3): ("flip", "同 r2：A=明确单件部分退款无法在线直接操作并转人工；B=SOP 要求复杂部分/多商品退款转人工→评测器把 capability limitation 误当成违反部分退款政策"),
    ("single", "v2_m_m9", 1): ("keep", "双意图：实际 q_product 结果包含 AirPods 与黑色运动鞋，回复'没有白色款的运动鞋'虽事实方向正确，但连续 q_product×4 发散；B=product-recommend 结果不理想只允许换同义词/上层品类再搜一次→规划真缺陷，Judge 把白色 AirPods 当白鞋的理由错误"),
    ("single", "v2_m_m9", 3): ("keep", "同 r1：回复事实方向正确，但 q_product×3 仍超出一次变体/上层品类重搜的 SOP；B=应收敛搜索，不扩散到其他品类→规划真缺陷，Judge 的白色 AirPods 归因错误"),
    # multi run3 FILL: handled separately below (assume pass, infra)
}


# 原始 evaluator 判为 PASS、但逐 trace 复核后仍发现 Agent 可见规则违例。
# 这些不是 FLIP：PASS 本身是评测器漏检，审计结论应为 KEEP_FAIL，报告标题因此标红。
RAW_PASS_ADJUDICATE: dict[tuple[str, str, int], tuple[str, str]] = {
    # SYSTEM_PROMPT 第 8 条：只能复述工具返回的绝对日期，不得说今天/明天/马上/很快等。
    ("single", "v2_c1_t01", 2): ("keep", "A=物流结论使用'预计明天（2024-01-19）'；B=SYSTEM_PROMPT 第8条只复述工具绝对日期，不使用相对时间→原始 PASS 漏检系统纪律违例"),
    ("single", "v2_c1_t02", 1): ("keep", "A=已给出 2024-01-19 后又说'预计明天送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c1_t02", 2): ("keep", "A=已给出 2024-01-19 后又说'预计明天就能送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c1_t02", 3): ("keep", "A=已给出 2024-01-19 后又说'预计明天（2024-01-19）就能送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c1_t07", 2): ("keep", "A=物流结论使用'预计明天就能送达'；B=SYSTEM_PROMPT 第8条只复述工具绝对日期→原始 PASS 漏检"),
    ("single", "v2_c2_t12", 1): ("keep", "A=已给出 2024-01-19 后又说'很快就能送到'；B=SYSTEM_PROMPT 第8条禁止相对时效→原始 PASS 漏检"),
    ("single", "v2_c2_t12", 2): ("keep", "A=已给出 2024-01-19 后又说'很快就能收到'；B=SYSTEM_PROMPT 第8条禁止相对时效→原始 PASS 漏检"),
    ("single", "v2_c3_t19", 2): ("keep", "A=取消订单仍说'现在需要为您发起退款'并准备确认后提交；B=取消状态/工具契约要求不得重复退款，store 的 apply_refund 也拒绝 cancelled→能力与状态处理真缺陷，原始 PASS 漏检"),
    ("single", "v2_c4_t23", 2): ("keep", "A=把工具时间'2024-01-18 08:30'说成'今天 08:30'；B=SYSTEM_PROMPT 第8条只复述绝对日期/时间→原始 PASS 漏检"),
    ("single", "v2_c4_t25", 1): ("keep", "A=仅凭 cancelled 的 query_order 结果断言'取消订单款项会在 1-3 个工作日原路退回'；B=SYSTEM_PROMPT 只复述工具事实，且该轮未检索退款政策→自动退款到账时效无证据，原始 PASS 漏检"),
    ("single", "v2_c4_t25", 2): ("keep", "A=仅凭 cancelled 状态断言已支付款项'应该已经按原路退回'并给出 1-3 个工作日；B=不得编造工具未返回的退款状态/到账时效→原始 PASS 漏检"),
    ("single", "v2_c5_t26", 2): ("keep", "A=已给出 2024-01-19 后又说'预计明天送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c5_t26", 3): ("keep", "A=已给出 2024-01-19 后又说'今天或明天就能收到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c6_t32", 2): ("keep", "A=已给出 2024-01-19 后又说'马上就到啦，今天'；B=SYSTEM_PROMPT 第8条禁止马上/今天等相对时间→原始 PASS 漏检"),
    ("single", "v2_c6_t32", 3): ("keep", "A=已给出 2024-01-19 后又说'预计明天就能送到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c6_t34", 1): ("keep", "A=已给出 2024-01-19 后又说'预计明天（1月19日）送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c6_t34", 2): ("keep", "A=使用'马上就能送到'和'今天就会送到'；B=SYSTEM_PROMPT 第8条只复述绝对日期→原始 PASS 漏检"),
    ("single", "v2_c6_t34", 3): ("keep", "A=已给出 2024-01-19 后又说'预计明天送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("single", "v2_c7_t39", 2): ("keep", "A=已给出 2024-01-19 后又说'预计明天送到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    # C5/MIXED：故障 504 后必须先用相同参数重试，不能插入物流调用。
    ("single", "v2_m_m5", 1): ("keep", "A=query_order 504 后先调 query_logistics，随后才重试 query_order；B=SYSTEM_PROMPT 第9条要求 504/5xx 先用相同参数重试一次→重试顺序真缺陷，原始 PASS 漏检"),
    ("single", "v2_m_m5", 2): ("keep", "A=query_order 504 后先调 query_logistics，随后才重试 query_order；B=SYSTEM_PROMPT 第9条要求先重试再进行后续查询→真缺陷，原始 PASS 漏检"),
    ("single", "v2_m_m5", 3): ("keep", "A=query_order 504 后先调 query_logistics，随后才重试 query_order；B=SYSTEM_PROMPT 第9条要求先重试再进行后续查询→真缺陷，原始 PASS 漏检"),
    # MULTI：同一系统纪律/状态纪律的漏检。
    ("multi", "v2_c1_t01", 1): ("keep", "A=已给出 2024-01-19 后又说'预计明天（1月19日）'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c1_t01", 2): ("keep", "A=已给出 1月19日后又说'今天应该就能到'；B=SYSTEM_PROMPT 第8条只复述工具绝对日期→原始 PASS 漏检"),
    ("multi", "v2_c1_t02", 1): ("keep", "A=物流结论使用'预计明天（1月19日）'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c1_t02", 3): ("keep", "A=已给出 2024-01-19 后又说'预计很快就能送达'；B=SYSTEM_PROMPT 第8条禁止相对时效→原始 PASS 漏检"),
    ("multi", "v2_c2_t12", 1): ("keep", "A=已给出 2024-01-19 后又说'明天就能送到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c2_t12", 3): ("keep", "A=已给出 01月19日后又说'今天或明天应该就能收到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c3_t19", 1): ("keep", "A=取消订单仍承诺'确认后我马上为您发起退款申请'；B=取消状态不得重复退款，工具契约/store 也拒绝 cancelled→状态处理真缺陷，原始 PASS 漏检"),
    ("multi", "v2_c3_t19", 2): ("keep", "A=仅凭 cancelled 状态断言款项会自动原路退回并给出 1-3 个工作日；B=SYSTEM_PROMPT 只复述工具/检索事实，该轮未检索退款政策→退款到账结论无证据，原始 PASS 漏检"),
    ("multi", "v2_c3_t19", 3): ("keep", "A=取消订单仍准备确认后'马上为您处理'退款；B=取消状态应说明自动退款/不得再次申请，不应引导 apply_refund→真缺陷，原始 PASS 漏检"),
    ("multi", "v2_c4_t23", 1): ("keep", "A=把正在派送说成'今天…可能马上就能送到'；B=SYSTEM_PROMPT 第8条只复述绝对日期/时间→原始 PASS 漏检"),
    ("multi", "v2_c4_t23", 2): ("keep", "A=已给出 2024-01-19 后又说'应该很快就能收到'；B=SYSTEM_PROMPT 第8条禁止相对时效→原始 PASS 漏检"),
    ("multi", "v2_c5_t26", 1): ("keep", "A=query_order 504 后先调 query_logistics，随后才重试 query_order，并使用'今天/明天'；B=第9条要求先重试，第8条禁止相对日期→两项真缺陷，原始 PASS 漏检"),
    ("multi", "v2_c5_t26", 2): ("keep", "A=已给出 2024-01-19 后又说'明天…很快'；B=SYSTEM_PROMPT 第8条禁止相对日期/时效→原始 PASS 漏检"),
    ("multi", "v2_c5_t26", 3): ("keep", "A=已给出 2024-01-19 后又说'今天或明天就能收到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c6_t32", 1): ("keep", "A=已给出 2024-01-19 后又说'明天/今天应该'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c6_t32", 3): ("keep", "A=使用'今天…明天'描述物流；B=SYSTEM_PROMPT 第8条只复述工具绝对日期→原始 PASS 漏检"),
    ("multi", "v2_c6_t34", 2): ("keep", "A=已给出 1月19日后又说'预计明天送达'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c6_t34", 3): ("keep", "A=使用'马上就到/今天晚些时候或明天'；B=SYSTEM_PROMPT 第8条禁止相对时效→原始 PASS 漏检"),
    ("multi", "v2_c6_t37", 1): ("keep", "A=已给出 2024-01-19 后又说'明天预计就能送到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c6_t37", 2): ("keep", "A=已给出 2024-01-19 后又说'明天应该就能到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c6_t37", 3): ("keep", "A=已给出 2024-01-19 后又说'马上就能到'；B=SYSTEM_PROMPT 第8条禁止相对时效→原始 PASS 漏检"),
    ("multi", "v2_c7_t39", 1): ("keep", "A=使用'明天/今天或明天'描述预计送达；B=SYSTEM_PROMPT 第8条只复述工具绝对日期→原始 PASS 漏检"),
    ("multi", "v2_c7_t39", 2): ("keep", "A=已给出 2024-01-19 后又说'今天应该就能收到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_c7_t39", 3): ("keep", "A=已给出 2024-01-19 后又说'预计明天就能送到'；B=SYSTEM_PROMPT 第8条禁止相对日期→原始 PASS 漏检"),
    ("multi", "v2_m_m5", 1): ("keep", "A=query_order 504 后先调 query_logistics，随后才重试 query_order，并使用'马上/明天'；B=第9条要求先重试，第8条禁止相对时间→真缺陷，原始 PASS 漏检"),
    ("multi", "v2_m_m7", 2): ("keep", "A=核对未签收事实时使用'今天 01-18'；B=SYSTEM_PROMPT 第8条只复述工具绝对日期/时间→原始 PASS 漏检"),
}


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


_PATHS = {
    "single": "artifacts/eval/20260904-104253/cases.jsonl",
    "multi": "artifacts/eval/20260905-024018/cases.jsonl",
}


def _load_raw(mode):
    out = {}
    for line in open(_PATHS[mode]):
        r = json.loads(line)
        out[(r["case_id"], r["run_index"])] = r
    return out


def _aggregate(mode, raw_rows):
    per = {}
    n_pass = 0
    total = 0
    n_complete = 0
    for (cid, run), r in raw_rows.items():
        total += 1
        per.setdefault(cid, 0)
        if r.get("complete"):
            n_complete += 1
        if r.get("passed") and r.get("complete") and not r.get("_audit_keep"):
            per[cid] += 1
            n_pass += 1
    return {"runs": total, "complete": sum(bool(r.get("complete")) for r in raw_rows.values()),
            "pass_rate": n_pass / n_complete if n_complete else None,
            "cases": len(per)}


def main():
    raw = json.load(open(ADJ))
    aus = raw["audit"]
    out_audit = {"single": [], "multi": []}
    raw_rows = {}
    counts = {"single": {"flip": 0, "keep": 0, "fill": 0, "raw_pass_keep": 0}, "multi": {"flip": 0, "keep": 0, "fill": 0, "raw_pass_keep": 0}}
    for mode in ("single", "multi"):
        raw_rows[mode] = _load_raw(mode)
        for a in aus[mode]:
            key = (mode, a["case"], a["run"])
            # Rebuild these entries below so rerunning this script stays idempotent.
            if key in RAW_PASS_ADJUDICATE:
                continue
            rr = raw_rows[mode].get((a["case"], a["run"]))
            if key in ADJUDICATE:
                verdict, evidence = ADJUDICATE[key]
                a["decision"] = "FLIP" if verdict == "flip" else "KEEP_FAIL"
                a["what"] = evidence
                counts[mode][verdict] += 1
                if verdict == "flip" and rr and rr.get("complete"):
                    # 按判决改 raw 的通过状态
                    rr["passed"] = True
            elif a.get("decision") == "FILL_ASSUM":
                counts[mode]["fill"] += 1
            elif a.get("decision") in ("KEEP_FAIL", "FLIP") and a.get("raw_status") == "PASS":
                continue  # 已从 RAW_PASS_ADJUDICATE 撤回 → 该轮恢复为原始 PASS，不写入 audit
            out_audit[mode].append(a)
        for (entry_mode, case_id, run_index), (verdict, evidence) in RAW_PASS_ADJUDICATE.items():
            if entry_mode != mode:
                continue
            rr = raw_rows[mode].get((case_id, run_index))
            if not rr or not (rr.get("complete") and rr.get("passed")):
                raise ValueError(f"raw-pass adjudication does not point to PASS row: {entry_mode}/{case_id}/r{run_index}")
            out_audit[mode].append({
                "case": case_id,
                "run": run_index,
                "raw_status": "PASS",
                "decision": "KEEP_FAIL" if verdict == "keep" else "FLIP",
                "what": evidence,
            })
            if verdict == "keep":
                counts[mode]["raw_pass_keep"] += 1
                rr["_audit_keep"] = True
    agg = {m: _aggregate(m, raw_rows[m]) for m in ("single", "multi")}
    OUT.write_text(json.dumps({"note": "manual adjusted vs agent-visible rules (A→B evidence per flip)",
                               "aggregates": agg, "counts": counts, "audit": out_audit},
                              ensure_ascii=False, indent=1))
    print("counts:", counts)
    print("aggregates:", agg)


if __name__ == "__main__":
    main()
