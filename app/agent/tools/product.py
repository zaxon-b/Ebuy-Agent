from app.agent.run_context import RunContext


def query_product(context: RunContext, keyword: str) -> dict:
    """根据商品名称关键词或商品ID查询商品信息，包括价格、库存、规格等。"""
    results = context.store.query_products(keyword)
    return {"success": True, "count": len(results), "products": results}
