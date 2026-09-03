FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn

COPY . .

# FDE-PATCH：在 agentscope 源码上打补丁（extra_factory 元组 + 定时任务默认本地时区）
RUN python scripts/patch_agentscope.py

EXPOSE 4000

ENV PYTHONUNBUFFERED=1
ENV PLATFORM_HOST=0.0.0.0
CMD ["python", "main.py"]
