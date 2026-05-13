# factor_registry.py
# -*- coding: utf-8 -*-

"""
v1.6.0 因子登记表

作用：
1. 记录当前选股系统使用了哪些因子
2. 标注因子用途、方向、当前状态、版本
3. 为后续实盘反馈和聚宽因子接入做准备

运行：
python factor_registry.py

输出：
1. output/factor_registry.csv
2. output/factor_registry.md
"""

from pathlib import Path

import pandas as pd


OUTPUT_DIR = Path("output")
CSV_FILE = OUTPUT_DIR / "factor_registry.csv"
MD_FILE = OUTPUT_DIR / "factor_registry.md"


def get_factor_registry() -> pd.DataFrame:
    """
    返回当前系统因子登记表
    """

    factors = [
        # =========================
        # 日线因子
        # =========================
        {
            "factor_name": "最新收盘价",
            "category": "日线因子",
            "description": "用于控制股票价格区间，适配3W小资金试盘",
            "direction": "价格在30-50元之间更适合当前资金规模",
            "current_status": "已使用",
            "used_in_version": "v1.0",
        },
        {
            "factor_name": "MA5",
            "category": "日线因子",
            "description": "用于判断短线趋势承接位置",
            "direction": "收盘价高于MA5且偏离不过大更优",
            "current_status": "已使用",
            "used_in_version": "v1.0",
        },
        {
            "factor_name": "距MA5偏离率",
            "category": "日线因子",
            "description": "判断是否追高，控制买入位置",
            "direction": "偏离率越小，越适合低吸；偏离过大扣分",
            "current_status": "已使用",
            "used_in_version": "v1.3",
        },
        {
            "factor_name": "最近5日涨幅",
            "category": "日线因子",
            "description": "判断短线是否过热",
            "direction": "涨幅适中较优，涨幅过高扣分或放弃",
            "current_status": "已使用",
            "used_in_version": "v1.0",
        },
        {
            "factor_name": "最近5日振幅",
            "category": "日线因子",
            "description": "判断是否具备隔日T空间",
            "direction": "振幅过低没有T空间，振幅过高风险偏大",
            "current_status": "已使用",
            "used_in_version": "v1.0",
        },
        {
            "factor_name": "最近5日平均成交额",
            "category": "日线因子",
            "description": "判断流动性，避免小成交额股票",
            "direction": "成交额越充足越好，但超大市值慢趋势票需后续降权",
            "current_status": "已使用",
            "used_in_version": "v1.0",
        },
        {
            "factor_name": "热点标签",
            "category": "日线因子",
            "description": "判断题材方向，辅助识别主线板块",
            "direction": "热点标签明确优于未归类",
            "current_status": "半可用",
            "used_in_version": "v1.1",
        },
        {
            "factor_name": "所属市场",
            "category": "日线因子",
            "description": "区分主板、创业板、科创板，排除北交所",
            "direction": "当前优先主板、创业板、科创板，排除北交所",
            "current_status": "已使用",
            "used_in_version": "v1.0",
        },

        # =========================
        # 分时因子
        # =========================
        {
            "factor_name": "今日开盘",
            "category": "分时因子",
            "description": "判断高开、低开和平开结构",
            "direction": "低开修复优于低开阴跌，高开不追",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "上午最高",
            "category": "分时因子",
            "description": "用于判断上午是否有冲高动作",
            "direction": "下午突破上午高点是转强信号",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "上午最低",
            "category": "分时因子",
            "description": "用于判断早盘是否急跌以及是否修复",
            "direction": "急跌后能修复并不再破低更优",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "午盘价",
            "category": "分时因子",
            "description": "判断上午结束时结构强弱",
            "direction": "午盘价远离高点说明冲高回落，需要尾盘再确认",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "今日最高",
            "category": "分时因子",
            "description": "用于计算收盘位置和是否尾盘创新高",
            "direction": "收盘接近今日最高更优",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "今日最低",
            "category": "分时因子",
            "description": "用于计算从低点修复幅度",
            "direction": "从低点修复幅度越强越好",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "收盘位置",
            "category": "分时因子",
            "description": "判断收盘位于全天振幅区间的位置",
            "direction": "收盘位置越高，尾盘资金越强",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "从低点修复幅度",
            "category": "分时因子",
            "description": "判断下跌后是否有资金修复",
            "direction": "修复幅度越大越好，但需结合收盘位置",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "从高点回落幅度",
            "category": "分时因子",
            "description": "判断是否冲高回落",
            "direction": "回落幅度过大说明追高资金被套",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "是否突破上午高点",
            "category": "分时因子",
            "description": "判断下午是否重新转强",
            "direction": "突破上午高点是尾盘转强信号",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "分时结构标签",
            "category": "分时因子",
            "description": "将分时走势归类为修复、阴跌、冲高回落再转强等",
            "direction": "冲高回落再转强、强势横盘优于全天阴跌",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },
        {
            "factor_name": "隔夜建议等级",
            "category": "分时因子",
            "description": "基于尾盘确认生成A/B/C/D等级",
            "direction": "A/B可进入交易池，C观察，D放弃",
            "current_status": "已使用",
            "used_in_version": "v1.5",
        },

        # =========================
        # 风控因子
        # =========================
        {
            "factor_name": "风险等级",
            "category": "风控因子",
            "description": "综合涨幅、振幅、MA5偏离率判断风险",
            "direction": "低风险优于中风险，高风险不进交易池",
            "current_status": "已使用",
            "used_in_version": "v1.3",
        },
        {
            "factor_name": "单票仓位",
            "category": "风控因子",
            "description": "控制单票3000-5000元",
            "direction": "避免单票过重，适合3W试盘",
            "current_status": "已使用",
            "used_in_version": "v1.2",
        },
        {
            "factor_name": "最大交易数量",
            "category": "风控因子",
            "description": "每日最多实际操作2只",
            "direction": "限制交易频率，避免临盘乱买",
            "current_status": "已使用",
            "used_in_version": "v1.2",
        },
        {
            "factor_name": "止损价",
            "category": "风控因子",
            "description": "根据MA5和振幅动态计算止损",
            "direction": "跌破计划止损价先退出，不补仓",
            "current_status": "已使用",
            "used_in_version": "v1.3",
        },

        # =========================
        # 未来聚宽因子
        # =========================
        {
            "factor_name": "总市值",
            "category": "未来聚宽因子",
            "description": "过滤过大慢趋势票，例如超大市值机构票",
            "direction": "当前策略更偏中等市值高活跃股票",
            "current_status": "待加入",
            "used_in_version": "planned_v1.7",
        },
        {
            "factor_name": "换手率",
            "category": "未来聚宽因子",
            "description": "判断活跃度和筹码交换",
            "direction": "适中换手优于过低或极端换手",
            "current_status": "待加入",
            "used_in_version": "planned_v1.7",
        },
        {
            "factor_name": "量比",
            "category": "未来聚宽因子",
            "description": "判断当日资金异动程度",
            "direction": "适度放量优于无量或爆量",
            "current_status": "待加入",
            "used_in_version": "planned_v1.7",
        },
        {
            "factor_name": "行业强度",
            "category": "未来聚宽因子",
            "description": "判断板块共振和主线延续",
            "direction": "板块强于大盘时加分",
            "current_status": "待加入",
            "used_in_version": "planned_v1.8",
        },
        {
            "factor_name": "资金流",
            "category": "未来聚宽因子",
            "description": "判断主力净流入和资金方向",
            "direction": "主力资金流入优于流出",
            "current_status": "待加入",
            "used_in_version": "planned_v1.8",
        },
        {
            "factor_name": "波动率",
            "category": "未来聚宽因子",
            "description": "区分是否具备稳定T空间",
            "direction": "适中波动率优于低波动和极端波动",
            "current_status": "待加入",
            "used_in_version": "planned_v1.8",
        },
        {
            "factor_name": "连续上涨天数",
            "category": "未来聚宽因子",
            "description": "防止接过热票",
            "direction": "连续上涨过多天需要扣分",
            "current_status": "待加入",
            "used_in_version": "planned_v1.8",
        },
    ]

    return pd.DataFrame(factors)


def export_factor_registry() -> None:
    """
    导出因子登记表
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = get_factor_registry()

    df.to_csv(
        CSV_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    md_lines = [
        "# 选股因子登记表",
        "",
        "版本：v1.6.0",
        "",
        "用途：记录当前系统使用的日线因子、分时因子、风控因子，以及未来计划加入的聚宽因子。",
        "",
    ]

    for category, group in df.groupby("category", sort=False):
        md_lines.append(f"## {category}")
        md_lines.append("")
        md_lines.append("| 因子 | 说明 | 方向 | 状态 | 使用版本 |")
        md_lines.append("| --- | --- | --- | --- | --- |")

        for _, row in group.iterrows():
            md_lines.append(
                f"| {row['factor_name']} | {row['description']} | "
                f"{row['direction']} | {row['current_status']} | {row['used_in_version']} |"
            )

        md_lines.append("")

    MD_FILE.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"因子登记表已生成：{CSV_FILE}")
    print(f"因子说明文档已生成：{MD_FILE}")
    print(f"因子数量：{len(df)}")


if __name__ == "__main__":
    export_factor_registry()