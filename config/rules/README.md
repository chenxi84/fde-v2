# 企业制度库（非结构化知识）

放**非结构化的制度/政策文件**（规章制度、作业指导书、SOP、行业规范、政策文件等），
格式 `.md` 或 `.txt`。

这些是「自由文本」知识，agent 通过 `platform_query_knowledge` 走知识图谱语义检索来查
（而不是像应用组的业务规则那样走 `platform_read_app_doc` 精确读）。

## 用法

放好制度文件后，建索引：

```bash
python -m fde_platform.knowledge_graph index rules
```

查询（手动验证）：

```bash
python -m fde_platform.knowledge_graph query rules "退货运费谁承担"
```

> 注意：应用组（app/）里的业务规则是**结构化**的，不需要放进这里；
> 本目录只放非结构化的制度/政策自由文本。
