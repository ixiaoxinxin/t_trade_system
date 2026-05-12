# sector_mapper.py
# -*- coding: utf-8 -*-

"""
A股板块 / 热点标签识别模块 v1.1-light

说明：
1. 不再请求 AKShare 板块接口
2. 不再请求东方财富板块接口
3. 避免 VPN / ProxyError / 运行过慢
4. 所属板块统一写：未标记
5. 热点标签只基于股票名称做轻量关键词识别
"""

import pandas as pd


def clean_text(value) -> str:
    """
    清洗文本
    """

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null"]:
        return ""

    return text


def build_hot_tag(stock_name: str) -> str:
    """
    基于股票名称做轻量热点标签识别
    """

    text = clean_text(stock_name)

    tag_rules = {
        "半导体": ["半导体", "芯片", "微电", "晶圆", "封测", "电子", "光电"],
        "AI": ["智能", "智算", "AI", "数据"],
        "算力": ["算力", "数据", "云", "服务器"],
        "CPO": ["光迅", "中际", "新易盛", "天孚", "光库", "光模块"],
        "机器人": ["机器人", "自动化", "机电", "电机", "精机"],
        "有色金属": ["铜", "铝", "锌", "铅", "钴", "镍", "锡", "钨", "钼", "锑", "稀土", "有色"],
        "黄金": ["黄金", "贵金属", "金矿", "赤峰", "山东黄金", "中金黄金"],
        "锂电池": ["锂", "电池", "天齐", "赣锋", "融捷", "永兴", "华友"],
        "固态电池": ["固态"],
        "化工": ["化工", "化学", "材料", "新材", "橡胶", "塑料"],
        "军工": ["军工", "航天", "航空", "兵器", "船舶", "北方", "中航"],
        "低空经济": ["低空", "无人机", "航空", "航天"],
        "消费电子": ["电子", "光电", "精密", "立讯", "歌尔", "蓝思"],
        "软件": ["软件", "信息", "信安", "网络", "科技"],
        "通信": ["通信", "通讯", "光迅", "中兴", "烽火"],
        "医药": ["医药", "医疗", "制药", "生物", "药业"],
        "新能源": ["新能源", "光伏", "风电", "储能", "电池", "锂"],
        "电力": ["电力", "能源", "水电", "火电", "核电"],
        "传媒": ["传媒", "影视", "出版", "游戏", "文化"],
        "汽车": ["汽车", "汽配", "车辆", "动力", "智能车"],
    }

    matched = []

    for tag, keywords in tag_rules.items():
        for keyword in keywords:
            if keyword in text:
                matched.append(tag)
                break

    if matched:
        return "；".join(matched)

    return "未归类"


def enrich_candidates_with_sector(
    candidates_df: pd.DataFrame,
    stock_df: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, dict]:
    """
    给候选股补充 所属板块 / 热点标签
    轻量版：不联网、不缓存、不请求AKShare板块
    """

    if candidates_df is None or candidates_df.empty:
        stats = {
            "候选股票数量": 0,
            "板块识别成功": 0,
            "板块未知": 0,
            "热点标签识别成功": 0,
            "未归类": 0,
            "板块缓存": "未使用",
        }
        return candidates_df, stats

    df = candidates_df.copy()

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    # 不再识别板块，避免网络和速度问题
    df["所属板块"] = "未标记"

    # 只基于股票名称识别热点标签
    df["热点标签"] = df["股票名称"].apply(build_hot_tag)

    total = len(df)
    hot_success = int((df["热点标签"] != "未归类").sum())
    hot_unknown = total - hot_success

    stats = {
        "候选股票数量": total,
        "板块识别成功": 0,
        "板块未知": total,
        "热点标签识别成功": hot_success,
        "未归类": hot_unknown,
        "板块缓存": "未使用",
    }

    return df, stats


def print_sector_stats(stats: dict):
    """
    打印统计日志
    """

    print("\n板块/热点标签识别统计：")
    print(f"候选股票数量：{stats.get('候选股票数量', 0)}")
    print(f"板块识别成功：{stats.get('板块识别成功', 0)}")
    print(f"板块未知：{stats.get('板块未知', 0)}")
    print(f"热点标签识别成功：{stats.get('热点标签识别成功', 0)}")
    print(f"未归类：{stats.get('未归类', 0)}")
    print(f"板块缓存：{stats.get('板块缓存', '未使用')}")