"""模拟外部系统 HTTP 服务——SAP / MOM / WMS 各一个端点，供集成接口测试。"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 5099

class Handler(BaseHTTPRequestHandler):
    def _respond(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        if "/sap/stock" in self.path:
            self._respond({"status": "ok", "material": "YADI-M8", "stock_qty": 150, "unit": "台"})
        elif "/mom/progress" in self.path:
            self._respond({"status": "ok", "order_no": "ORD-001", "progress": "生产中", "eta": "2026-08-10"})
        elif "/wms/inventory" in self.path:
            self._respond({"status": "ok", "warehouse": "WH-01", "items": [{"sku":"Y8","qty":20},{"sku":"M8","qty":15}]})
        else:
            self._respond({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        if "/sap/create_kb" in self.path:
            self._respond({"status": "ok", "kb_no": "KB-20260805-001", "message": "开博单已创建"})
        elif "/mom/submit" in self.path:
            self._respond({"status": "ok", "mom_order": "MOM-889", "message": "已提交生产"})
        elif "/wms/ship" in self.path:
            self._respond({"status": "ok", "shipment": "SHIP-456", "message": "已出库"})
        else:
            self._respond({"error": "not found"}, 404)

    def log_message(self, format, *args):
        print(f"[mock-ext] {args[0]}")  # 简洁日志


if __name__ == "__main__":
    print(f"Mock 外部系统启动: http://127.0.0.1:{PORT}")
    print(f"  GET  http://127.0.0.1:{PORT}/sap/stock")
    print(f"  POST http://127.0.0.1:{PORT}/sap/create_kb")
    print(f"  GET  http://127.0.0.1:{PORT}/mom/progress")
    print(f"  POST http://127.0.0.1:{PORT}/wms/ship")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
