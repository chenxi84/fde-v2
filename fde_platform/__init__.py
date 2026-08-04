"""FDE v2 平台运行时。

目录不叫 `platform` 以免遮蔽 Python 标准库 `platform` 模块
（应用需将仓库根加入 sys.path 以 `import fde`，若本包同名会让 openai/flask 等
依赖标准库 platform 的库失效）。
"""
