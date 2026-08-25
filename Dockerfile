FROM python:3.11-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn

EXPOSE 4000

ENV PYTHONUNBUFFERED=1
ENV PLATFORM_HOST=0.0.0.0
CMD ["python", "main.py"]
