"""
测试用工具服务器 —— 运行在 8502 端口，供 AgentNexus-J HTTP 工具接入测试。

启动方式：
    uv run python tool_server.py
    或
    python tool_server.py

提供的工具端点：
    POST http://localhost:8502/text-stats   {"text": "..."}  → 文本统计
    POST http://localhost:8502/calculator   {"expression": "1+2*3"}  → 简单计算
"""

import re
import ast
import operator
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="AgentNexus 测试工具服务")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── 工具 1：文本统计 ──────────────────────────────────────────────────────────

class TextStatsRequest(BaseModel):
    text: str


@app.post("/text-stats")
def text_stats(req: TextStatsRequest):
    text = req.text
    lines = text.splitlines()
    words = re.findall(r"\S+", text)
    chinese_chars = re.findall(r"[一-鿿]", text)
    return {
        "字符数（含空格）": len(text),
        "字符数（不含空格）": len(text.replace(" ", "")),
        "汉字数": len(chinese_chars),
        "单词/词语数": len(words),
        "行数": len(lines),
        "段落数": len([l for l in lines if l.strip()]),
    }


# ── 工具 2：安全计算器 ────────────────────────────────────────────────────────

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"不支持的操作: {ast.dump(node)}")


class CalcRequest(BaseModel):
    expression: str


@app.post("/calculator")
def calculator(req: CalcRequest):
    try:
        tree = ast.parse(req.expression.strip(), mode="eval")
        result = _safe_eval(tree.body)
        return {"expression": req.expression, "result": result}
    except Exception as e:
        return {"expression": req.expression, "error": str(e)}


@app.get("/health")
def health():
    return {"status": "ok", "tools": ["/text-stats", "/calculator"]}


if __name__ == "__main__":
    print("🛠  测试工具服务启动中...")
    print("   文本统计: POST http://localhost:8502/text-stats")
    print("   计算器:   POST http://localhost:8502/calculator")
    uvicorn.run(app, host="0.0.0.0", port=8502)
