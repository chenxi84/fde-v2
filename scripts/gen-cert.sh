#!/bin/bash
# 生成自签证书（仅用于内网 / 测试；公网请用 Let's Encrypt）

mkdir -p certs
openssl req -x509 -nodes -days 3650 \
  -subj "/CN=fde-v2-internal" \
  -newkey rsa:2048 \
  -keyout certs/key.pem \
  -out certs/cert.pem

chmod 600 certs/key.pem
echo "证书已生成到 certs/ 目录"
echo "用于内网 HTTPS，浏览器访问时请点「继续访问」"
