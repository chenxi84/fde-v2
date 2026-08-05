"""FDE groupbuild 构建 CRM 应用组自动化脚本"""
import requests
import json
import time
import sys

BASE = "http://127.0.0.1:4000"
GROUP = "yadi_crm"

BRD_CONTENT = """# 雅迪电动车门店 CRM 系统

## 业务背景
为销售雅迪电动车的门店开发一套客户关系管理系统，帮助门店管理从获客到售后的全流程。

## 涉及角色
- 店长：管理门店整体运营，查看报表
- 销售顾问：跟进客户和商机，处理订单
- 客服：处理客户投诉和售后问题
- 仓管：管理车辆库存

## 核心业务流程

### 1. 客户管理
- 录入客户信息（姓名、电话、意向车型、来源渠道等）
- 对客户进行分级（A/B/C/D）
- 记录客户跟进历史

### 2. 商机管理
- 创建商机并关联客户
- 记录商机阶段（初步接洽 → 需求分析 → 试驾体验 → 报价谈判 → 签约成交 → 交付完成）
- 设置预计成交金额和预计成交日期

### 3. 订单管理
- 根据商机生成销售订单
- 订单包含客户信息、车型、数量、金额、付款方式
- 跟踪订单状态（待付款 → 已付款 → 配车中 → 已交付 → 已完成）

### 4. 库存管理
- 管理车辆入库和出库
- 记录车辆信息（车型、颜色、车架号、电池规格、入库时间）
- 库存查询和预警

### 5. 客诉管理
- 记录客户投诉信息（投诉类型、投诉内容、关联订单）
- 跟踪处理进度（已受理 → 处理中 → 已完成 → 客户回访）
- 记录处理结果和客户满意度

## 数据关系
- 客户可以有多个商机
- 商机可以生成一个订单
- 订单关联多辆车（库存商品）
- 客诉可关联到客户和订单
"""


def main():
    s = requests.Session()

    # 1. Login
    print("=== 登录 ===")
    r = s.post(f"{BASE}/login", data={"username": "admin", "password": "admin"}, allow_redirects=False)
    print(f"  登录: {r.status_code}")

    # 2. Upload BRD file
    print("=== 上传 BRD ===")
    files = {"file": ("业务需求.md", BRD_CONTENT.encode("utf-8"), "text/markdown; charset=utf-8")}
    r = s.post(f"{BASE}/api/groupbuild/groups/{GROUP}/files", files=files)
    print(f"  上传: {json.dumps(r.json(), ensure_ascii=False)}")

    # 3. Trigger architecture build (step ①)
    print("=== 触发架构构建 (第①步) ===")
    r = s.post(f"{BASE}/api/groupbuild/groups/{GROUP}/architecture", json={
        "business_text": "请给销售雅迪电动车的门店开发一个CRM客户关系管理系统，主要包括客户管理、商机管理、订单管理、库存管理、客诉管理"
    })
    print(f"  触发: {json.dumps(r.json(), ensure_ascii=False)}")

    # 4. Poll task status
    if r.json().get("data") and r.json()["data"].get("task_id"):
        task_id = r.json()["data"]["task_id"]
        print(f"\n=== 监控任务 #{task_id} ===")
        for _ in range(120):  # 最多等 120 秒
            time.sleep(3)
            r = s.get(f"{BASE}/api/groupbuild/tasks/{task_id}")
            t = r.json().get("data", {})
            status = t.get("status", "?")
            step = t.get("current_step", "?")
            log_tail = t.get("log", "")[-200:] if t.get("log") else ""
            print(f"  状态: {status}, 当前步骤: {step}")
            if log_tail:
                print(f"  日志: ...{log_tail}")
            if status in ("done", "failed", "cancelled"):
                print(f"\n=== 最终状态: {status} ===")
                if t.get("error"):
                    print(f"  错误: {t['error']}")
                print(f"  完整日志:\n{t.get('log', '')[-1000:]}")
                break
    else:
        print(f"  响应: {json.dumps(r.json(), ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
