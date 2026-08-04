# e2e 模块契约速查（自动生成 · 视图生成参照）

> 字段以本文件与 `app/e2e/<应用>/<应用>.py` 源码为准；list 示例为真实返回（无数据项以源码为准）。


## member

### 服务契约
```
create(member_no*, name*, email*, role*)
get(member_no*)
list(keyword=None:string, role=None:string, page=None:integer, page_size=None:integer)
```

### 返回示例
（暂无数据 —— 字段读源码 get()/INSERT）


## task

### 服务契约
```
complete(task_no*)
create(title*, description=None:string, assignee_member_no=None:string, priority=None:string)
get(task_no*)
list(status=None:string, assignee_member_no=None:string, priority=None:string, page=None:string, page_size=None:string)
reopen(task_no*)
start(task_no*)
```

### 返回示例
（暂无数据 —— 字段读源码 get()/INSERT）
