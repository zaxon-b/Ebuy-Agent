from app.agent.run_context import RunContext


def query_logistics(context: RunContext, order_id: str) -> dict:
    """根据订单号查询物流轨迹信息。

    硬前置：仅已发货（shipped）/已签收（delivered）的订单可查询物流；
    待发货（pending）等状态直接拒绝，返回未发货提示，避免在错误状态上调用。
    """
    order = context.store.get_order(order_id, user_id=context.current_user_id)
    if not order:
        return {"success": False, "error": f"未找到订单 {order_id}，请核实订单号"}
    if order["status"] == "pending":
        return {
            "success": False,
            "error_code": "logistics_unavailable",
            "error": "该订单尚未发货，暂无物流信息",
            "order_status": "pending",
        }
    logistics = context.store.get_logistics(
        order_id=order_id, user_id=context.current_user_id
    )
    if logistics is None:
        return {"success": False, "error": f"未找到订单 {order_id}，请核实订单号"}
    if not logistics.get("available"):
        return {
            "success": False,
            "error_code": "logistics_unavailable",
            "error": logistics["error"],
            "order_status": logistics["order_status"],
        }
    return {"success": True, "logistics": logistics}