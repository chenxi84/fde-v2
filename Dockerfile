FROM python:3.10-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

EXPOSE 4000

ENV PYTHONUNBUFFERED=1
ENV PLATFORM_HOST=0.0.0.0
CMD ["python", "main.py"]
