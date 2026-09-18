# e2e 模块契约速查（自动生成 · 视图生成参照）

> 字段以此文件与 `app/e2e/<应用>/<应用>.py` 源码为准；list 示例取自库中现有数据（无数据项以源码为准；造数级样例经平台⑧契约冻结任务生成）。


## member

### 服务契约
```
create(member_no*, name*, email*, role*)
get(member_no*)
list(keyword=None:string, role=None:string, page=None:integer, size=None:integer)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "member_no": "M001",
 "name": "张管理",
 "email": "m001@example.com",
 "role": "admin"
}
```


## task

### 服务契约
```
complete(task_no*)
create(title*, description=None:string, assignee_member_no=None:string, priority=None:string)
get(task_no*)
list(status=None:string, assignee_member_no=None:string, priority=None:string, page=None:integer, size=None:integer)
reopen(task_no*)
start(task_no*)
```

### get/list 示例
（未造出样例 —— 字段请读源码 get()/INSERT 语句）

### list 返回项示例
```json
{
 "task_no": "T707CE6619BE548BE945CE9BDB77AB02E",
 "title": "已完成锁",
 "description": null,
 "assignee_member_no": "M002",
 "priority": "low",
 "status": "已完成",
 "created_at": "2026-09-17 07:57:08.784683",
 "updated_at": "2026-09-17 07:57:08.806897"
}
```
