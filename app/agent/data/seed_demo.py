"""Versioned deterministic demo seed migrated from ``tools/mock_data.py``."""

from __future__ import annotations

import json
import sqlite3


ORDERS = [
    {
        "order_id": "ORD-20240115-001",
        "user_id": "user-demo",
        "status": "shipped",
        "items": [
            {
                "name": "Nike Air Max 270 运动鞋",
                "sku": "SHOE-270-BK-42",
                "quantity": 1,
                "price": 899.0,
            }
        ],
        "shipping_address": "上海市浦东新区",
        "total_amount": 899.0,
        "tracking_number": "SF1234567890",
        "carrier": "顺丰速运",
        "logistics_status": "in_transit",
        "events": [
            {"time": "2024-01-16 14:20", "location": "深圳南山区", "description": "快件已揽收"},
            {"time": "2024-01-17 06:00", "location": "广州转运中心", "description": "已到达"},
            {"time": "2024-01-17 22:00", "location": "上海转运中心", "description": "已到达"},
            {"time": "2024-01-18 08:30", "location": "上海浦东区", "description": "正在派送中"},
        ],
        "estimated_delivery": "2024-01-19",
        "delivered_at": None,
        "created_at": "2024-01-15 10:30:00",
    },
    {
        "order_id": "ORD-20240120-002",
        "user_id": "user-demo",
        "status": "pending",
        "items": [
            {"name": "Apple AirPods Pro 2", "sku": "ELEC-APP-002", "quantity": 1, "price": 1799.0},
            {"name": "AirPods 保护壳（透明）", "sku": "ACC-AP-CASE-01", "quantity": 1, "price": 29.9},
        ],
        "shipping_address": "北京市海淀区",
        "total_amount": 1828.9,
        "tracking_number": None,
        "carrier": None,
        "logistics_status": None,
        "events": [],
        "estimated_delivery": None,
        "delivered_at": None,
        "created_at": "2024-01-20 09:15:00",
    },
    {
        "order_id": "ORD-20240110-003",
        "user_id": "user-demo",
        "status": "delivered",
        "items": [
            {"name": "小米14 Ultra 手机", "sku": "PHONE-MI14U-BK", "quantity": 1, "price": 5999.0}
        ],
        "shipping_address": "北京市海淀区",
        "total_amount": 5999.0,
        "tracking_number": "JD9876543210",
        "carrier": "京东物流",
        "logistics_status": "delivered",
        "events": [
            {"time": "2024-01-11 08:00", "location": "北京亦庄仓库", "description": "快件已出库"},
            {"time": "2024-01-12 10:00", "location": "北京海淀区", "description": "正在派送中"},
            {"time": "2024-01-13 11:30", "location": "北京海淀区", "description": "已签收"},
        ],
        "estimated_delivery": "2024-01-13",
        "delivered_at": "2024-01-13 11:30:00",
        "created_at": "2024-01-10 16:00:00",
    },
    {
        "order_id": "ORD-20240118-004",
        "user_id": "user-demo",
        "status": "refund_processing",
        "items": [
            {"name": "Levi's 501 经典牛仔裤", "sku": "CLOTH-LEVI-501-30", "quantity": 1, "price": 699.0}
        ],
        "shipping_address": "上海市普陀区",
        "total_amount": 699.0,
        "tracking_number": "YT6655443322",
        "carrier": "圆通速递",
        "logistics_status": "delivered",
        "events": [
            {"time": "2024-01-19 09:00", "location": "杭州余杭区", "description": "快件已揽收"},
            {"time": "2024-01-20 06:00", "location": "杭州转运中心", "description": "已发出"},
            {"time": "2024-01-20 18:00", "location": "上海转运中心", "description": "已到达"},
            {"time": "2024-01-21 09:00", "location": "上海普陀区", "description": "正在派送中"},
            {"time": "2024-01-21 15:00", "location": "上海普陀区", "description": "已签收"},
        ],
        "estimated_delivery": "2024-01-22",
        "delivered_at": "2024-01-21 15:00:00",
        "created_at": "2024-01-18 12:00:00",
    },
    {
        "order_id": "ORD-20240122-005",
        "user_id": "user-alt",
        "status": "pending",
        "items": [
            {"name": "戴森 V15 吸尘器", "sku": "HOME-DYSON-V15", "quantity": 1, "price": 4299.0},
            {"name": "戴森 V15 替换滤芯", "sku": "HOME-DYSON-FLTR", "quantity": 2, "price": 199.0},
        ],
        "shipping_address": "杭州市余杭区",
        "total_amount": 4697.0,
        "tracking_number": None,
        "carrier": None,
        "logistics_status": None,
        "events": [],
        "estimated_delivery": None,
        "delivered_at": None,
        "created_at": "2024-01-22 20:00:00",
    },
    {
        "order_id": "ORD-20240105-006",
        "user_id": "user-demo",
        "status": "refunded",
        "items": [{"name": "AirPods 保护壳（透明）", "sku": "ACC-AP-CASE-01", "quantity": 1, "price": 29.9}],
        "shipping_address": "上海市浦东新区",
        "total_amount": 29.9,
        "tracking_number": None,
        "carrier": None,
        "logistics_status": None,
        "events": [],
        "estimated_delivery": None,
        "delivered_at": None,
        "created_at": "2024-01-05 08:00:00",
    },
    {
        "order_id": "ORD-20240106-007",
        "user_id": "user-demo",
        "status": "cancelled",
        "items": [{"name": "Apple AirPods Pro 2", "sku": "ELEC-APP-002", "quantity": 1, "price": 1799.0}],
        "shipping_address": "上海市浦东新区",
        "total_amount": 1799.0,
        "tracking_number": None,
        "carrier": None,
        "logistics_status": None,
        "events": [],
        "estimated_delivery": None,
        "delivered_at": None,
        "created_at": "2024-01-06 08:00:00",
    },
    {
        "order_id": "ORD-20240123-008",
        "user_id": "user-alt",
        "status": "shipped",
        "items": [{"name": "戴森 V15 Detect 吸尘器", "sku": "HOME-DYSON-V15", "quantity": 1, "price": 4299.0}],
        "shipping_address": "杭州市余杭区",
        "total_amount": 4299.0,
        "tracking_number": "SF0000000008",
        "carrier": "顺丰速运",
        "logistics_status": "in_transit",
        "events": [
            {"time": "2024-01-24 09:00", "location": "上海仓库", "description": "快件已出库"},
            {"time": "2024-01-25 12:00", "location": "杭州转运中心", "description": "运输中"},
        ],
        "estimated_delivery": "2024-01-26",
        "delivered_at": None,
        "created_at": "2024-01-23 20:00:00",
    },
]


PRODUCTS = [
    ("SHOE-270-BK-42", "Nike Air Max 270 运动鞋", "运动鞋", 899.0, 156, "经典气垫缓震，透气网面鞋身，适合日常跑步和休闲穿搭", {"颜色": "黑色", "尺码": "42", "材质": "网面+合成革"}, 1),
    ("ELEC-APP-002", "Apple AirPods Pro 2", "耳机", 1799.0, 89, "主动降噪，自适应透明模式，个性化空间音频，USB-C 充电", {"颜色": "白色", "连接方式": "蓝牙5.3", "续航": "6小时(ANC开启)"}, 1),
    ("PHONE-MI14U-BK", "小米14 Ultra 手机", "手机", 5999.0, 42, "骁龙8 Gen3，徕卡光学四摄，2K 护眼屏，5000mAh 大电池", {"颜色": "黑色", "存储": "16GB+512GB", "屏幕": "6.73英寸 2K AMOLED"}, 1),
    ("CLOTH-LEVI-501-30", "Levi's 501 经典牛仔裤", "牛仔裤", 699.0, 0, "经典直筒版型，原色丹宁面料，纽扣门襟", {"颜色": "原色", "尺码": "30", "材质": "100%棉"}, 1),
    ("HOME-DYSON-V15", "戴森 V15 Detect 吸尘器", "家电", 4299.0, 23, "激光探测微尘，LCD 屏幕实时显示吸入颗粒", {"颜色": "金色", "续航": "60分钟", "吸力": "230AW"}, 1),
    ("ACC-AP-CASE-01", "AirPods 保护壳（透明）", "配件", 29.9, 500, "TPU 透明软壳，防摔防刮，精准开孔", {"材质": "TPU", "适配": "AirPods Pro 2"}, 1),
]


REFUNDS = [
    ("REF-ORD-20240118-004", "ORD-20240118-004", "尺码不合适", "processing", "2024-01-22 10:00:00"),
    ("REF-ORD-20240105-006", "ORD-20240105-006", "不想要了", "completed", "2024-01-07 10:00:00"),
]


def seed_demo(conn: sqlite3.Connection) -> None:
    """Insert the versioned demo fixture into an empty schema."""
    conn.executemany(
        """
        INSERT INTO orders (
            order_id, user_id, status, items_json, shipping_address,
            total_amount, tracking_number, carrier, logistics_status,
            logistics_events_json, estimated_delivery, delivered_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                order["order_id"], order["user_id"], order["status"],
                json.dumps(order["items"], ensure_ascii=False),
                order["shipping_address"], order["total_amount"],
                order["tracking_number"], order["carrier"],
                order["logistics_status"],
                json.dumps(order["events"], ensure_ascii=False),
                order["estimated_delivery"], order["delivered_at"],
                order["created_at"],
            )
            for order in ORDERS
        ],
    )
    conn.executemany(
        """
        INSERT INTO products (
            product_id, name, category, price, stock, description,
            specs_json, is_refundable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(*row[:6], json.dumps(row[6], ensure_ascii=False), row[7]) for row in PRODUCTS],
    )
    conn.executemany(
        """
        INSERT INTO refunds (refund_id, order_id, reason, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        REFUNDS,
    )
    conn.commit()
