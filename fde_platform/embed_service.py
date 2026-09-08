"""FDE v2 — 独立 embedding 服务（文本 → 向量）。

把「BGE + torch」从主进程（main.py / agent_service）里抽出来，单独跑一个进程，
全平台只有这里 import torch。主进程经 ``FDE_EMBED_URL`` 走 HTTP 调 ``POST /embed``，
自身不 import torch——内存紧张（如 2核2G 服务器 / 本机多进程）时避免多份 torch 常驻。

用法：
    python -m fde_platform.embed_service            # :9800
    FDE_KG_EMBED_MODEL=BAAI/bge-m3 python -m fde_platform.embed_service   # 换模型

配置（环境变量）：
    FDE_KG_EMBED_MODEL  bge 模型名（默认 BAAI/bge-small-zh-v1.5）
    FDE_KG_EMBED_DIM    向量维度（默认 512，须与模型一致）
    HF_ENDPOINT         国内下载 bge 用 https://hf-mirror.com
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

EMBED_MODEL = os.environ.get("FDE_KG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_DIM = int(os.environ.get("FDE_KG_EMBED_DIM", "512"))

# 国内默认走 HF 镜像（主进程 knowledge_graph 也设了，这里独立进程再兜底一次）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_model = None


def _get_model():
    """惰性加载 bge（首个请求才 import torch + 下载/加载模型）。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """文本列表 → 归一化向量列表（同步，供 HTTP handler 调用）。"""
    return _get_model().encode(texts, normalize_embeddings=True).tolist()


class EmbedReq(BaseModel):
    texts: list[str]


app = FastAPI(title="FDE embed service")


@app.get("/")
def health():
    return {"ok": True, "model": EMBED_MODEL, "dim": EMBED_DIM}


@app.post("/embed")
def embed(req: EmbedReq):
    if not req.texts:
        return {"vectors": [], "dim": EMBED_DIM}
    return {"vectors": embed_texts(req.texts), "dim": EMBED_DIM}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fde_platform.embed_service:app", host="0.0.0.0", port=9800)
