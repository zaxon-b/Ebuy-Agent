from app.agent.run_context import RunContext

STATUS_LABELS = {
    "pending": "待发货",
    "shipped": "已发货",
    "delivered": "已签收",
    "refund_processing": "退款中",
    "refunded": "已退款",
    "cancelled": "已取消",
}


def list_user_orders(context: RunContext) -> dict:
    """查询当前用户的所有订单概要列表。"""
    user_orders = context.store.list_orders(user_id=context.current_user_id)
    orders = [
        {
            "order_id": o["order_id"],
            "status": STATUS_LABELS.get(o["status"], o["status"]),
            "items_summary": "、".join(item["name"] for item in o["items"]),
            "total": o["total_amount"],
            "created_at": o["created_at"],
        }
        for o in user_orders
    ]
    return {"success": True, "count": len(orders), "orders": orders}
