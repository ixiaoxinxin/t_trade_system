# sector_mapper.py
# -*- coding: utf-8 -*-

"""
A股板块与热点标签识别模块 v1.0 bugfix

功能：
1. 使用 AKShare 获取行业板块信息
2. 使用 AKShare 获取概念板块信息
3. 生成 output/sector_cache.csv 缓存
4. 基于：所属板块 + 概念列表 + 股票名称 生成热点标签
5. AKShare 请求失败时不影响主程序运行
"""

import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except Exception:
    ak = None


OUTPUT_DIR = Path("output")
CACHE_FILE = OUTPUT_DIR / "sector_cache.csv"


def normalize_code(code: str) -> str:
    """
    标准化股票代码，保留6位字符串
    """

    return str(code).strip().zfill(6)


def is_cache_valid(cache_file: Path = CACHE_FILE) -> bool:
    """
    判断缓存是否为当天生成
    """

    if not cache_file.exists():
        return False

    cache_date = datetime.fromtimestamp(cache_file.stat().st_mtime).date()
    today = datetime.now().date()

    return cache_date == today


def clean_text(value) -> str:
    """
    清洗文本字段
    """

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text in ["nan", "None", "null"]:
        return ""

    return text


def build_hot_tag(stock_name: str, industry: str, concept_list: str) -> str:
    """
    基于 股票名称 + 所属行业 + 概念列表 生成热点标签
    """

    stock_name = clean_text(stock_name)
    industry = clean_text(industry)
    concept_list = clean_text(concept_list)

    text = f"{stock_name} {industry} {concept_list}"

    tag_rules = {
        "半导体": [
            "半导体", "芯片", "集成电路", "晶圆", "封测", "光刻机", "光刻胶",
            "第三代半导体", "功率半导体", "存储芯片", "先进封装", "电子元件",
            "电子器件", "PCB", "IGBT"
        ],
        "AI": [
            "AI", "人工智能", "大模型", "ChatGPT", "AIGC", "多模态", "机器学习",
            "智能体", "语料", "数据要素"
        ],
        "算力": [
            "算力", "服务器", "液冷", "数据中心", "IDC", "云计算", "边缘计算",
            "GPU", "英伟达", "华为昇腾"
        ],
        "CPO": [
            "CPO", "光模块", "光通信", "光器件", "光芯片", "高速连接器",
            "硅光", "800G", "1.6T"
        ],
        "机器人": [
            "机器人", "人形机器人", "工业机器人", "减速器", "伺服", "电机",
            "传感器", "机器视觉", "自动化设备"
        ],
        "有色金属": [
            "有色", "有色金属", "铜", "铝", "锌", "铅", "钴", "镍", "锡",
            "钨", "钼", "锑", "稀土", "小金属", "工业金属"
        ],
        "黄金": [
            "黄金", "贵金属", "金矿", "白银"
        ],
        "锂电池": [
            "锂电", "锂电池", "锂矿", "碳酸锂", "电池", "正极", "负极",
            "隔膜", "电解液", "六氟磷酸锂", "钴酸锂", "磷酸铁锂", "三元材料"
        ],
        "固态电池": [
            "固态电池", "半固态电池", "硫化物电解质", "氧化物电解质"
        ],
        "化工": [
            "化工", "化学", "化学制品", "化学原料", "新材料", "氟化工",
            "磷化工", "煤化工", "农药", "染料", "涂料", "塑料", "橡胶"
        ],
        "军工": [
            "军工", "国防军工", "航空", "航天", "兵器", "导弹", "雷达",
            "军民融合", "船舶", "卫星导航", "北斗"
        ],
        "低空经济": [
            "低空经济", "无人机", "eVTOL", "飞行汽车", "通用航空", "空管",
            "航空器"
        ],
        "消费电子": [
            "消费电子", "苹果", "华为", "小米", "手机", "MR", "VR", "AR",
            "智能穿戴", "耳机", "折叠屏"
        ],
        "软件": [
            "软件", "信创", "操作系统", "数据库", "网络安全", "信息安全",
            "国产软件", "SaaS", "工业软件"
        ],
        "通信": [
            "通信", "5G", "6G", "通信设备", "运营商", "基站", "卫星通信",
            "物联网", "车联网"
        ],
        "医药": [
            "医药", "医疗", "创新药", "生物医药", "中药", "CXO", "疫苗",
            "医疗器械", "减肥药", "合成生物"
        ],
        "新能源": [
            "新能源", "光伏", "风电", "储能", "氢能", "太阳能", "逆变器",
            "充电桩", "特高压"
        ],
        "电力": [
            "电力", "火电", "水电", "核电", "绿电", "电网", "智能电网",
            "虚拟电厂", "电力设备"
        ],
        "传媒": [
            "传媒", "游戏", "影视", "短剧", "出版", "广告", "文化传媒",
            "IP", "院线"
        ],
        "汽车": [
            "汽车", "新能源汽车", "汽车零部件", "智能驾驶", "无人驾驶",
            "车联网", "整车", "汽配", "热管理", "线控底盘"
        ],
    }

    matched_tags = []

    for tag, keywords in tag_rules.items():
        for keyword in keywords:
            if keyword in text:
                matched_tags.append(tag)
                break

    if matched_tags:
        return "；".join(matched_tags)

    if industry:
        return industry

    if concept_list:
        first_concept = concept_list.split("；")[0]
        return first_concept if first_concept else "未归类"

    return "未归类"


def get_industry_map() -> dict:
    """
    获取行业板块映射：
    股票代码 -> 行业名称

    优先使用 AKShare 行业板块成分接口
    """

    industry_map = {}

    if ak is None:
        print("AKShare 未安装，无法获取行业板块")
        return industry_map

    try:
        industry_names = ak.stock_board_industry_name_em()

        if industry_names is None or industry_names.empty:
            print("行业板块列表为空")
            return industry_map

        if "板块名称" not in industry_names.columns:
            print(f"行业板块字段异常：{list(industry_names.columns)}")
            return industry_map

        industry_list = industry_names["板块名称"].dropna().astype(str).tolist()

        print(f"开始获取行业板块数量：{len(industry_list)}")

        for index, industry_name in enumerate(industry_list, start=1):
            try:
                print(f"行业板块 {index}/{len(industry_list)}：{industry_name}")

                cons = ak.stock_board_industry_cons_em(symbol=industry_name)

                if cons is None or cons.empty:
                    continue

                if "代码" not in cons.columns:
                    continue

                for _, row in cons.iterrows():
                    code = normalize_code(row["代码"])
                    industry_map[code] = industry_name

                time.sleep(0.15)

            except Exception as e:
                print(f"行业板块获取失败：{industry_name}，原因：{e}")
                continue

    except Exception as e:
        print(f"获取行业板块总表失败：{e}")

    return industry_map


def get_concept_map() -> dict:
    """
    获取概念板块映射：
    股票代码 -> 概念列表
    """

    concept_map = {}

    if ak is None:
        print("AKShare 未安装，无法获取概念板块")
        return concept_map

    try:
        concept_names = ak.stock_board_concept_name_em()

        if concept_names is None or concept_names.empty:
            print("概念板块列表为空")
            return concept_map

        if "板块名称" not in concept_names.columns:
            print(f"概念板块字段异常：{list(concept_names.columns)}")
            return concept_map

        concept_list = concept_names["板块名称"].dropna().astype(str).tolist()

        print(f"开始获取概念板块数量：{len(concept_list)}")

        for index, concept_name in enumerate(concept_list, start=1):
            try:
                print(f"概念板块 {index}/{len(concept_list)}：{concept_name}")

                cons = ak.stock_board_concept_cons_em(symbol=concept_name)

                if cons is None or cons.empty:
                    continue

                if "代码" not in cons.columns:
                    continue

                for _, row in cons.iterrows():
                    code = normalize_code(row["代码"])

                    if code not in concept_map:
                        concept_map[code] = []

                    concept_map[code].append(concept_name)

                time.sleep(0.12)

            except Exception as e:
                print(f"概念板块获取失败：{concept_name}，原因：{e}")
                continue

    except Exception as e:
        print(f"获取概念板块总表失败：{e}")

    result = {}

    for code, concepts in concept_map.items():
        unique_concepts = list(dict.fromkeys(concepts))
        result[code] = "；".join(unique_concepts)

    return result


def generate_sector_cache(stock_df: pd.DataFrame) -> pd.DataFrame:
    """
    重新生成板块缓存
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stock_df = stock_df.copy()

    stock_df["代码"] = stock_df["代码"].astype(str).apply(normalize_code)

    if "名称" not in stock_df.columns:
        stock_df["名称"] = ""

    industry_map = get_industry_map()
    concept_map = get_concept_map()

    rows = []

    for _, row in stock_df.iterrows():
        code = normalize_code(row["代码"])
        name = clean_text(row.get("名称", ""))

        industry = clean_text(industry_map.get(code, ""))
        concepts = clean_text(concept_map.get(code, ""))

        # 如果没有行业，但有概念，则先用第一个概念兜底为所属板块
        if industry:
            sector = industry
        elif concepts:
            sector = concepts.split("；")[0]
        else:
            sector = "未知"

        hot_tag = build_hot_tag(
            stock_name=name,
            industry=sector if sector != "未知" else "",
            concept_list=concepts
        )

        rows.append({
            "股票代码": code,
            "股票名称": name,
            "所属板块": sector,
            "概念列表": concepts,
            "热点标签": hot_tag,
        })

    cache_df = pd.DataFrame(rows)

    cache_df["股票代码"] = cache_df["股票代码"].astype(str).str.zfill(6)

    cache_df.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")

    return cache_df


def get_sector_cache(stock_df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """
    获取板块缓存

    返回：
        cache_df: 板块缓存 DataFrame
        cache_hit: 是否命中缓存
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if is_cache_valid(CACHE_FILE):
        try:
            cache_df = pd.read_csv(CACHE_FILE, dtype={"股票代码": str})
            cache_df["股票代码"] = cache_df["股票代码"].astype(str).str.zfill(6)

            required_cols = ["股票代码", "股票名称", "所属板块", "概念列表", "热点标签"]
            missing_cols = [col for col in required_cols if col not in cache_df.columns]

            if not missing_cols:
                return cache_df, True

        except Exception as e:
            print(f"读取板块缓存失败，将重新生成：{e}")

    cache_df = generate_sector_cache(stock_df)

    return cache_df, False


def enrich_candidates_with_sector(
    candidates_df: pd.DataFrame,
    stock_df: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """
    给候选股 DataFrame 补充 所属板块 / 热点标签 / 概念列表
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

    candidates_df = candidates_df.copy()
    candidates_df["股票代码"] = candidates_df["股票代码"].astype(str).str.zfill(6)

    cache_df, cache_hit = get_sector_cache(stock_df)

    cache_df = cache_df.copy()
    cache_df["股票代码"] = cache_df["股票代码"].astype(str).str.zfill(6)

    sector_cols = ["股票代码", "所属板块", "概念列表", "热点标签"]

    merged_df = candidates_df.drop(
        columns=[col for col in ["所属板块", "热点标签", "概念列表"] if col in candidates_df.columns],
        errors="ignore"
    ).merge(
        cache_df[sector_cols],
        on="股票代码",
        how="left"
    )

    merged_df["所属板块"] = merged_df["所属板块"].fillna("未知")
    merged_df["概念列表"] = merged_df["概念列表"].fillna("")
    merged_df["热点标签"] = merged_df["热点标签"].fillna("未归类")

    # 二次兜底：如果热点标签仍未归类，用当前行信息再算一次
    for idx, row in merged_df.iterrows():
        sector = clean_text(row.get("所属板块", ""))
        concept = clean_text(row.get("概念列表", ""))
        name = clean_text(row.get("股票名称", ""))

        if row.get("热点标签", "") in ["", "未归类"]:
            merged_df.at[idx, "热点标签"] = build_hot_tag(
                stock_name=name,
                industry=sector if sector != "未知" else "",
                concept_list=concept
            )

    total = len(merged_df)
    sector_success = int((merged_df["所属板块"] != "未知").sum())
    sector_unknown = total - sector_success

    hot_success = int((merged_df["热点标签"] != "未归类").sum())
    hot_unknown = total - hot_success

    stats = {
        "候选股票数量": total,
        "板块识别成功": sector_success,
        "板块未知": sector_unknown,
        "热点标签识别成功": hot_success,
        "未归类": hot_unknown,
        "板块缓存": "命中" if cache_hit else "重新生成",
    }

    return merged_df, stats


def print_sector_stats(stats: dict):
    """
    打印识别统计
    """

    print("\n板块/热点标签识别统计：")
    print(f"候选股票数量：{stats.get('候选股票数量', 0)}")
    print(f"板块识别成功：{stats.get('板块识别成功', 0)}")
    print(f"板块未知：{stats.get('板块未知', 0)}")
    print(f"热点标签识别成功：{stats.get('热点标签识别成功', 0)}")
    print(f"未归类：{stats.get('未归类', 0)}")
    print(f"板块缓存：{stats.get('板块缓存', '未知')}")