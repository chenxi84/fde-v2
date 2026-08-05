"""测试应用——模拟含外部系统适配器的聚合根，供集成接口页面发现和测试。"""
from fde import FdeError


class MockExt:
    def _init_db(self):
        self.db.execute("CREATE TABLE IF NOT EXISTS mock_ext (id INTEGER PRIMARY KEY)")

    # 公共服务
    def ping(self):
        return {"status": "ok"}

    # 外部系统适配器（会被集成接口页面扫描到）
    def _sap_query_stock(self, material: str):
        """查询 SAP 库存。"""
        return {"target": "SAP", "action": "query_stock", "material": material}

    def _sap_create_order(self, order_data: dict):
        """向 SAP 创建订单。"""
        return {"target": "SAP", "action": "create_order", "data": order_data}

    def _mom_get_progress(self, order_no: str):
        """查询 MOM 生产进度。"""
        return {"target": "MOM", "action": "get_progress", "order_no": order_no}

    def _wms_check_stock(self, sku: str):
        """查询 WMS 库存。"""
        return {"target": "WMS", "action": "check_stock", "sku": sku}
