# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

from common import load_yaml_config, safe_float


CONFIG_FILE = Path("config.yaml")

DEFAULT_PUSHPLUS_CONFIG = {
    "enabled": True,
    "url": "https://www.pushplus.plus/send",
    "token": os.getenv("PUSHPLUS_TOKEN", "b75b94a8e3ac44db9237ad16c3a4b170"),
}


def escape(value: Any) -> str:
    text = "" if pd.isna(value) else str(value)
    return html.escape(text.strip())


def num(value: Any, digits: int = 2, default: str = "-") -> str:
    parsed = safe_float(value, None)
    if parsed is None:
        return default
    return f"{parsed:.{digits}f}".rstrip("0").rstrip(".")


def pct(value: Any, digits: int = 1, default: str = "-") -> str:
    parsed = safe_float(value, None)
    if parsed is None:
        return default
    return f"{parsed:.{digits}f}%"


def pushplus_config() -> dict[str, Any]:
    defaults = {"sell_signal": {"pushplus": DEFAULT_PUSHPLUS_CONFIG}}
    config = load_yaml_config(CONFIG_FILE, defaults)
    return config.get("sell_signal", {}).get("pushplus", DEFAULT_PUSHPLUS_CONFIG)


def send_pushplus_message(title: str, content: str, template: str = "html") -> bool:
    config = pushplus_config()
    if not config.get("enabled", True):
        print("PushPlus 未启用。")
        return False

    token = str(config.get("token") or "").strip()
    if not token:
        print("PushPlus token 为空，跳过推送。")
        return False

    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": template,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        str(config.get("url", DEFAULT_PUSHPLUS_CONFIG["url"])),
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            print(f"PushPlus 返回：{raw}")
            return True
    except Exception as exc:
        print(f"PushPlus 推送失败：{exc}")
        return False


def mobile_css() -> str:
    return """
<style>
*{box-sizing:border-box}
body{margin:0;background:#0f1117;color:#eef1f6;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif;font-size:16px;line-height:1.45}
.wrap{max-width:520px;margin:0 auto;padding:14px 12px 22px}
.top{padding:8px 2px 12px;border-bottom:1px solid #2b303a}
h1{margin:0 0 6px;font-size:24px;line-height:1.18}
h2{margin:18px 0 10px;font-size:18px}
.muted{color:#969daa;font-size:13px}
.summary{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.summary div,.card{background:#171a22;border:1px solid #2c323d;border-radius:12px}
.summary div{padding:10px}
.label{color:#9aa3b2;font-size:12px;margin-bottom:3px}
.value{font-size:20px;font-weight:700}
.card{padding:12px;margin:10px 0}
.card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:8px}
.name{font-size:18px;font-weight:800}
.code{display:block;color:#9aa3b2;font-size:12px;margin-top:2px}
.badge{flex:0 0 auto;border-radius:999px;padding:4px 9px;font-size:13px;font-weight:700}
.danger{background:#431e24;color:#ff8d95}
.warn{background:#43381c;color:#ffd166}
.ok{background:#173826;color:#7ee787}
.info{background:#1e2a44;color:#9ecbff}
.action{font-size:17px;font-weight:800;margin:7px 0}
.reason{color:#d7dce5;margin:6px 0 10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.cell{background:#10131a;border:1px solid #272d37;border-radius:9px;padding:8px}
.cell strong{display:block;margin-top:2px;font-size:16px}
.full{grid-column:1/-1}
.section-note{padding:9px 10px;border-left:3px solid #ff4d57;background:#171a22;color:#d7dce5;border-radius:8px}
</style>
"""


def page(title: str, subtitle: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
{mobile_css()}
</head>
<body>
<main class="wrap">
<section class="top">
<h1>{escape(title)}</h1>
<div class="muted">{escape(subtitle)}</div>
</section>
{body}
</main>
</body>
</html>"""


def signal_badge_class(signal: str) -> str:
    if signal in {"止损", "清仓"}:
        return "danger"
    if signal in {"止盈", "减仓"}:
        return "warn"
    if signal in {"持有", "继续持有", "可低吸"}:
        return "ok"
    return "info"


def build_mobile_sell_signal_html(signal_df: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if signal_df.empty:
        return page("A股隔日T卖点信号", f"生成时间：{now}", '<div class="card">暂无卖点信号。</div>')

    fixed_series = signal_df["固定持仓"].astype(str) if "固定持仓" in signal_df.columns else pd.Series([""] * len(signal_df), index=signal_df.index)

    body = [
        '<div class="summary">',
        f'<div><div class="label">信号数</div><div class="value">{len(signal_df)}</div></div>',
        f'<div><div class="label">固定持仓</div><div class="value">{int(fixed_series.eq("是").sum())}</div></div>',
        "</div>",
        '<div class="section-note">手机端只展示影响操作的字段：动作、理由、当前价、涨幅、回撤和均线状态。</div>',
    ]

    fixed_mask = fixed_series.eq("是")
    fixed_df = signal_df[fixed_mask].copy()
    other_df = signal_df[~fixed_mask].copy()
    sections = [("固定持仓", fixed_df), ("候选/其他", other_df)]

    for section_title, section_df in sections:
        if section_df.empty:
            continue
        body.append(f"<h2>{escape(section_title)}</h2>")
        for _, row in section_df.iterrows():
            signal = escape(row.get("卖出信号", "观察"))
            cls = signal_badge_class(str(row.get("卖出信号", "")))
            body.append(f"""
<article class="card">
  <div class="card-head">
    <div class="name">{escape(row.get("股票名称", ""))}<span class="code">{escape(row.get("股票代码", ""))}</span></div>
    <div class="badge {cls}">{signal}</div>
  </div>
  <div class="action">操作：{signal}</div>
  <div class="reason">{escape(row.get("卖出理由", ""))}</div>
  <div class="grid">
    <div class="cell"><span class="label">当前价</span><strong>{num(row.get("当前价"))}</strong></div>
    <div class="cell"><span class="label">当前涨幅</span><strong>{pct(row.get("当前涨幅"))}</strong></div>
    <div class="cell"><span class="label">高点回撤</span><strong>{pct(row.get("高点回撤"))}</strong></div>
    <div class="cell"><span class="label">保持率</span><strong>{pct(row.get("冲高保持率"))}</strong></div>
    <div class="cell"><span class="label">均线状态</span><strong>{escape(row.get("均线状态", ""))}</strong></div>
    <div class="cell"><span class="label">隔夜等级</span><strong>{escape(row.get("隔夜等级", ""))}</strong></div>
  </div>
</article>""")

    return page("A股隔日T卖点信号", f"生成时间：{now}", "\n".join(body))


def build_mobile_opening_levels_html(levels_df: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if levels_df.empty:
        return page("开盘T区间", f"生成时间：{now}", '<div class="card">暂无开盘T区间。</div>')

    status_series = levels_df["状态"].astype(str) if "状态" in levels_df.columns else pd.Series([""] * len(levels_df), index=levels_df.index)

    body = [
        '<div class="summary">',
        f'<div><div class="label">股票数</div><div class="value">{len(levels_df)}</div></div>',
        f'<div><div class="label">可操作</div><div class="value">{int(status_series.eq("成功").sum())}</div></div>',
        "</div>",
        '<div class="section-note">开盘先看买进区间和卖出区间，AI只做辅助解释，最终按行情和纪律执行。</div>',
    ]

    for _, row in levels_df.iterrows():
        action = str(row.get("操作", "先观察"))
        cls = signal_badge_class(action)
        body.append(f"""
<article class="card">
  <div class="card-head">
    <div class="name">{escape(row.get("股票名称", ""))}<span class="code">{escape(row.get("股票代码", ""))}</span></div>
    <div class="badge {cls}">{escape(action)}</div>
  </div>
  <div class="action">操作：{escape(action)}</div>
  <div class="reason">{escape(row.get("AI辅助", row.get("算法依据", "")))}</div>
  <div class="grid">
    <div class="cell"><span class="label">买进区间</span><strong>{escape(row.get("买进区间", ""))}</strong></div>
    <div class="cell"><span class="label">卖出区间</span><strong>{escape(row.get("卖出区间", ""))}</strong></div>
    <div class="cell"><span class="label">支撑位</span><strong>{num(row.get("支撑位"), 3)}</strong></div>
    <div class="cell"><span class="label">压力位</span><strong>{num(row.get("压力位"), 3)}</strong></div>
    <div class="cell"><span class="label">当前价</span><strong>{num(row.get("当前价"), 3)}</strong></div>
    <div class="cell"><span class="label">竞价/开盘</span><strong>{num(row.get("集合竞价价"), 3)}</strong></div>
    <div class="cell full"><span class="label">更新时间</span><strong>{escape(row.get("实时行情时间", row.get("刷新时间", "")))}</strong></div>
  </div>
</article>""")

    return page("开盘T区间", f"生成时间：{now}", "\n".join(body))
