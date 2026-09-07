"""FDE 冒烟测试 —— 部署后自动验证核心功能。"""
import sys, json, urllib.request, urllib.error

opener = None  # 登录后持有会话 cookie 的 opener（test 复用，避免默认 urlopen 不带 cookie 导致 401）


def test(name, url, method="GET", data=None, expect_status=200):
    try:
        req = urllib.request.Request(url, method=method)
        if data:
            req.add_header("Content-Type", "application/json")
            data_bytes = json.dumps(data).encode()
        else:
            data_bytes = None
        resp = opener.open(req, data=data_bytes, timeout=10)
        body = resp.read().decode(errors="replace")
        ok = resp.status == expect_status
        print(f"  {'OK' if ok else 'FAIL'}  {name} ({resp.status})")
        if not ok:
            print(f"     body: {body[:200]}")
        return ok
    except urllib.error.HTTPError as e:
        print(f"  FAIL  {name} (HTTP {e.code})")
        return False
    except Exception as e:
        print(f"  FAIL  {name} ({e})")
        return False


def main(host):
    BASE = f"http://{host}:4000"
    print(f"冒烟测试: {BASE}")

    # 登录
    import http.cookiejar
    import urllib.parse
    global opener
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    login_data = urllib.parse.urlencode({"username": "admin", "password": "admin"}).encode()
    opener.open(f"{BASE}/login", data=login_data)

    ok = 0
    fail = 0

    if test("首页可访问", f"{BASE}/"):
        ok += 1
    else:
        fail += 1

    if test("应用列表 API", f"{BASE}/api/apps"):
        ok += 1
    else:
        fail += 1

    if test("E2E: member.create", f"{BASE}/api/apps/e2e/member/call/create", method="POST",
            data={"member_no": "M-TEST", "name": "冒烟测试", "email": "smoke@test.com", "role": "member"}):
        ok += 1
    else:
        fail += 1

    if test("E2E: task.create", f"{BASE}/api/apps/e2e/task/call/create", method="POST",
            data={"title": "冒烟测试任务", "assignee_member_no": "M-TEST", "priority": "low"}):
        ok += 1
    else:
        fail += 1

    print(f"\n结果: {ok}/{ok+fail} 通过")
    return fail == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/smoke_test.py <服务器IP>")
        sys.exit(1)
    sys.exit(0 if main(sys.argv[1]) else 1)
