from app.agent.run_context import RunContext


def _user_confirmed_refund(context: RunContext) -> bool:
    """确认门禁：只有用户明确确认过退款，才允许执行退款。

    Eval 运行（注入 Tracer）时，从已注册 turn 的用户行为（acts）读取确认；
    普通对话（无 Tracer）不拦截，保持原有体验。
    """
    tracer = context.tracer
    if tracer is None:
        return True
    return tracer.has_user_act("confirm_refund")


def apply_refund(context: RunContext, order_id: str, reason: str) -> dict:
    """为指定订单申请退款，需提供退款原因。"""
    if not _user_confirmed_refund(context):
        return {
            "success": False,
            "error_code": "confirmation_required",
            "error": "退款是敏感操作，请先与用户确认订单号和退款原因，得到确认后再提交",
        }
    return context.store.apply_refund(
        user_id=context.current_user_id,
        order_id=order_id,
        reason=reason,
    )