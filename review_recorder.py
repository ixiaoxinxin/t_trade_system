# review_recorder.py
# -*- coding: utf-8 -*-

"""
v1.6-intraday-review 分时结构复盘模块

功能：
1. 读取 output/overnight_t_candidates.csv
2. 手动录入候选股盘中结构表现
3. 追加保存到 output/intraday_review_log.csv
4. 按日期生成 output/intraday_review.md
5. 不修改任何现有选股逻辑
"""

from pathlib import Path
from datetime import datetime

import pandas as pd


CANDIDATE_FILE = Path("output/overnight_t_candidates.csv")
REVIEW_LOG_FILE = Path("output/intraday_review_log.csv")
REVIEW_MD_FILE = Path("output/intraday_review.md")


REVIEW_COLUMNS = [
    "日期",
    "股票代码",
    "股票名称",
    "昨日综合评分",
    "昨日热点标签",
    "上午结构标签",
    "下午结构标签",
    "尾盘结构标签",
    "最终结果",
    "是否适合买入",
    "次日是否验证成功",
    "备注",
]


STRUCTURE_TAGS = [
    "全天阴跌型",
    "急跌修复成功型",
    "急跌修复失败型",
    "冲高回落再转强型",
    "强势横盘型",
    "高波动震荡型",
]


FINAL_RESULTS = [
    "强",
    "中",
    "弱",
    "放弃",
]


YES_NO_UNKNOWN = [
    "是",
    "否",
    "待验证",
]


def ensure_output_dir():
    """
    确保 output 目录存在
    """

    REVIEW_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def normalize_code(code) -> str:
    """
    股票代码统一为6位字符串
    """

    return str(code).strip().zfill(6)


def ensure_review_log_exists():
    """
    如果 intraday_review_log.csv 不存在，则自动创建
    """

    ensure_output_dir()

    if not REVIEW_LOG_FILE.exists():
        empty_df = pd.DataFrame(columns=REVIEW_COLUMNS)
        empty_df.to_csv(REVIEW_LOG_FILE, index=False, encoding="utf-8-sig")


def load_candidates() -> pd.DataFrame:
    """
    读取候选池
    """

    if not CANDIDATE_FILE.exists():
        raise FileNotFoundError(f"找不到候选池文件：{CANDIDATE_FILE}")

    df = pd.read_csv(CANDIDATE_FILE, dtype={"股票代码": str})

    if df.empty:
        raise ValueError("候选池为空，无法录入复盘")

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    if "综合评分" in df.columns:
        df["综合评分"] = pd.to_numeric(df["综合评分"], errors="coerce")
        df = df.sort_values("综合评分", ascending=False).reset_index(drop=True)

    return df


def load_review_log() -> pd.DataFrame:
    """
    读取历史复盘日志
    """

    ensure_review_log_exists()

    df = pd.read_csv(REVIEW_LOG_FILE, dtype={"股票代码": str})

    if df.empty:
        return pd.DataFrame(columns=REVIEW_COLUMNS)

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    return df


def save_review_log(df: pd.DataFrame):
    """
    保存复盘日志
    """

    df = df.copy()

    for col in REVIEW_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[REVIEW_COLUMNS]
    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    df.to_csv(REVIEW_LOG_FILE, index=False, encoding="utf-8-sig")


def select_from_list(title: str, options: list[str]) -> str:
    """
    命令行选择器
    """

    print(f"\n{title}")

    for i, option in enumerate(options, start=1):
        print(f"{i}. {option}")

    while True:
        user_input = input("请输入序号：").strip()

        if user_input.isdigit():
            index = int(user_input)

            if 1 <= index <= len(options):
                return options[index - 1]

        print("输入无效，请重新输入。")


def input_text(title: str, default: str = "") -> str:
    """
    文本输入
    """

    value = input(f"{title}（默认：{default}）：").strip()

    if value == "":
        return default

    return value


def build_review_row(candidate_row: pd.Series, review_date: str) -> dict:
    """
    为单只股票手动录入复盘
    """

    code = normalize_code(candidate_row.get("股票代码", ""))
    name = str(candidate_row.get("股票名称", ""))
    score = candidate_row.get("综合评分", "")
    hot_tag = str(candidate_row.get("热点标签", ""))

    print("\n" + "=" * 80)
    print(f"录入复盘：{code} {name}")
    print(f"昨日综合评分：{score}")
    print(f"昨日热点标签：{hot_tag}")

    morning_tag = select_from_list("选择上午结构标签", STRUCTURE_TAGS)
    afternoon_tag = select_from_list("选择下午结构标签", STRUCTURE_TAGS)
    late_tag = select_from_list("选择尾盘结构标签", STRUCTURE_TAGS)
    final_result = select_from_list("选择最终结果", FINAL_RESULTS)
    suitable_buy = select_from_list("是否适合买入", ["是", "否"])
    next_day_success = select_from_list("次日是否验证成功", YES_NO_UNKNOWN)
    remark = input_text("备注", "")

    return {
        "日期": review_date,
        "股票代码": code,
        "股票名称": name,
        "昨日综合评分": score,
        "昨日热点标签": hot_tag,
        "上午结构标签": morning_tag,
        "下午结构标签": afternoon_tag,
        "尾盘结构标签": late_tag,
        "最终结果": final_result,
        "是否适合买入": suitable_buy,
        "次日是否验证成功": next_day_success,
        "备注": remark,
    }


def append_reviews(review_rows: list[dict]):
    """
    追加复盘记录
    """

    if not review_rows:
        print("没有新增复盘记录。")
        return

    old_df = load_review_log()
    new_df = pd.DataFrame(review_rows)

    combined_df = pd.concat([old_df, new_df], ignore_index=True)

    save_review_log(combined_df)

    print(f"\n已追加 {len(review_rows)} 条复盘记录到：{REVIEW_LOG_FILE}")


def generate_markdown_for_date(review_date: str):
    """
    按日期生成 Markdown 复盘
    """

    df = load_review_log()

    if df.empty:
        md = f"# 分时结构复盘\n\n日期：{review_date}\n\n暂无复盘记录。\n"
        REVIEW_MD_FILE.write_text(md, encoding="utf-8")
        return

    day_df = df[df["日期"].astype(str) == review_date].copy()

    if day_df.empty:
        md = f"# 分时结构复盘\n\n日期：{review_date}\n\n暂无复盘记录。\n"
        REVIEW_MD_FILE.write_text(md, encoding="utf-8")
        return

    total = len(day_df)
    strong_count = int((day_df["最终结果"] == "强").sum())
    mid_count = int((day_df["最终结果"] == "中").sum())
    weak_count = int((day_df["最终结果"] == "弱").sum())
    abandon_count = int((day_df["最终结果"] == "放弃").sum())
    buy_count = int((day_df["是否适合买入"] == "是").sum())

    lines = []

    lines.append("# 分时结构复盘")
    lines.append("")
    lines.append(f"日期：{review_date}")
    lines.append("")
    lines.append("## 一、复盘统计")
    lines.append("")
    lines.append(f"- 复盘股票数量：{total}")
    lines.append(f"- 强：{strong_count}")
    lines.append(f"- 中：{mid_count}")
    lines.append(f"- 弱：{weak_count}")
    lines.append(f"- 放弃：{abandon_count}")
    lines.append(f"- 适合买入：{buy_count}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、逐股复盘")
    lines.append("")

    for _, row in day_df.iterrows():
        lines.append(f"### {row['股票代码']} {row['股票名称']}")
        lines.append("")
        lines.append(f"- 昨日综合评分：{row['昨日综合评分']}")
        lines.append(f"- 昨日热点标签：{row['昨日热点标签']}")
        lines.append(f"- 上午结构标签：{row['上午结构标签']}")
        lines.append(f"- 下午结构标签：{row['下午结构标签']}")
        lines.append(f"- 尾盘结构标签：{row['尾盘结构标签']}")
        lines.append(f"- 最终结果：{row['最终结果']}")
        lines.append(f"- 是否适合买入：{row['是否适合买入']}")
        lines.append(f"- 次日是否验证成功：{row['次日是否验证成功']}")
        lines.append(f"- 备注：{row['备注']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 三、策略优化提示")
    lines.append("")
    lines.append("- 如果“高评分但最终结果弱”的股票较多，说明前一日筛选条件需要加风险过滤。")
    lines.append("- 如果“急跌修复成功型”次日验证成功率高，可作为后续低吸模型重点样本。")
    lines.append("- 如果“强势横盘型”经常次日继续走强，可作为隔日T优先观察结构。")
    lines.append("- 如果“全天阴跌型”集中出现在某类热点标签，说明该热点短线退潮。")
    lines.append("")

    md = "\n".join(lines)

    REVIEW_MD_FILE.write_text(md, encoding="utf-8")

    print(f"Markdown 复盘已生成：{REVIEW_MD_FILE}")


def record_reviews():
    """
    主流程：选择候选股并录入复盘
    """

    ensure_review_log_exists()

    candidates = load_candidates()

    print("\n候选池前20只：")
    show_cols = [
        "股票代码",
        "股票名称",
        "热点标签",
        "最新收盘价",
        "MA5",
        "综合评分",
    ]

    existing_show_cols = [col for col in show_cols if col in candidates.columns]

    top20 = candidates.head(20).copy()

    print(top20[existing_show_cols].to_string(index=True))

    review_date = input_text(
        "\n请输入复盘日期 YYYY-MM-DD",
        datetime.now().strftime("%Y-%m-%d")
    )

    selected = input_text(
        "请输入要复盘的序号，多个用英文逗号分隔，例如 0,1,2；直接回车默认前5只",
        ""
    )

    if selected == "":
        selected_indexes = list(top20.index[:5])
    else:
        selected_indexes = []

        for item in selected.split(","):
            item = item.strip()

            if item.isdigit():
                index = int(item)

                if index in top20.index:
                    selected_indexes.append(index)

    review_rows = []

    for index in selected_indexes:
        row = top20.loc[index]
        review_row = build_review_row(row, review_date)
        review_rows.append(review_row)

    append_reviews(review_rows)
    generate_markdown_for_date(review_date)


def generate_only():
    """
    只根据已有 CSV 日志生成 Markdown
    """

    review_date = input_text(
        "请输入要生成 Markdown 的日期 YYYY-MM-DD",
        datetime.now().strftime("%Y-%m-%d")
    )

    generate_markdown_for_date(review_date)


def main():
    """
    命令行入口
    """

    print("\nA股隔日T选股系统 v1.6-intraday-review")
    print("1. 录入今日分时结构复盘")
    print("2. 只生成指定日期 Markdown 复盘")

    choice = input("请选择功能：").strip()

    if choice == "1":
        record_reviews()
    elif choice == "2":
        generate_only()
    else:
        print("输入无效，程序结束。")


if __name__ == "__main__":
    main()