# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
import traceback

from common import PRODUCT_VERSION, now_text
from run_manifest import write_run_manifest


COMMANDS = {
    "market": {
        "description": "生成市场环境报告",
        "runner": ("market_environment", "run_market_environment"),
        "outputs": [
            "output/market_environment.csv",
            "output/market_environment.md",
            "output/market_environment.json",
        ],
    },
    "candidates": {
        "description": "扫描隔日T候选池",
        "runner": ("strategy_overnight_t", "run_strategy"),
        "outputs": ["output/overnight_t_candidates.csv"],
    },
    "tail": {
        "description": "尾盘确认并生成最终观察池",
        "runner": ("tail_confirmation", "run_tail_confirmation"),
        "outputs": ["output/final_watchlist.csv", "output/final_watchlist.md"],
    },
    "plan": {
        "description": "生成明日交易计划",
        "runner": ("report_generator", "generate_daily_plan"),
        "outputs": ["output/daily_plan.md"],
    },
    "lunch": {
        "description": "生成午盘验证报告",
        "runner": ("lunch_validator", "run_lunch_validation"),
        "outputs": ["output/lunch_review.csv", "output/lunch_review.md"],
    },
    "sell": {
        "description": "生成卖点信号",
        "runner": ("sell_signal_engine", "run_sell_signal_engine"),
        "outputs": ["output/sell_signal.csv", "output/sell_signal.md"],
    },
    "next-day": {
        "description": "生成次日验证报告",
        "runner": ("next_day_validator", "run_next_day_validation"),
        "outputs": ["output/next_day_review.csv", "output/next_day_review.md", "output/factor_performance.csv"],
    },
    "review": {
        "description": "生成人工复盘案例库",
        "runner": ("review_manager", "export_review_cases"),
        "outputs": ["output/review_cases.jsonl", "output/review_cases.md"],
    },
    "factor-rank": {
        "description": "生成因子表现排行榜",
        "runner": ("factor_ranker", "export_factor_rank"),
        "outputs": ["output/factor_rank.csv", "output/factor_rank.md"],
    },
    "dataset": {
        "description": "生成 v2.5 训练数据集与标签系统",
        "runner": ("dataset_builder", "build_dataset"),
        "outputs": [
            "data/dataset/trade_dataset.sqlite3",
            "data/dataset/splits/latest.json",
            "output/dataset_quality_report.md",
        ],
    },
    "migrate-db": {
        "description": "迁移本地页面数据与行情缓存到 SQLite",
        "runner": ("sqlite_store", "migrate_local_files_to_sqlite"),
        "outputs": ["data/dataset/trade_dataset.sqlite3"],
    },
    "labels": {
        "description": "计算 v2.5 标签并写入 SQLite",
        "runner": ("label_calculator", "run_label_calculator"),
        "outputs": ["data/dataset/trade_dataset.sqlite3"],
    },
    "split": {
        "description": "生成 v2.5 时间序列训练/验证/测试切分",
        "runner": ("dataset_splitter", "run_dataset_splitter"),
        "outputs": ["data/dataset/splits/latest.json"],
    },
    "quality": {
        "description": "生成 v2.5 数据质量报告与标签复核队列",
        "runner": ("dataset_quality_report", "run_dataset_quality_report"),
        "outputs": ["output/dataset_quality_report.md", "output/label_review_queue.md"],
    },
}


PIPELINE = ["market", "candidates", "tail", "plan"]


def call_runner(command_name: str, max_count: int | None = None) -> dict:
    spec = COMMANDS[command_name]
    module_name, function_name = spec["runner"]

    started_at = now_text()

    try:
        module = __import__(module_name)
        runner = getattr(module, function_name)

        if command_name == "candidates":
            runner(max_count=max_count)
        else:
            runner()

        return {
            "name": command_name,
            "description": spec["description"],
            "success": True,
            "started_at": started_at,
            "finished_at": now_text(),
            "outputs": spec["outputs"],
        }

    except Exception as exc:
        return {
            "name": command_name,
            "description": spec["description"],
            "success": False,
            "started_at": started_at,
            "finished_at": now_text(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "outputs": spec["outputs"],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"A股隔日T选股系统 v{PRODUCT_VERSION} 统一入口",
    )

    choices = ["pipeline", *COMMANDS.keys()]

    parser.add_argument(
        "command",
        choices=choices,
        help="要执行的模块。pipeline 会执行 market -> candidates -> tail -> plan。",
    )
    parser.add_argument(
        "--max-count",
        type=int,
        default=None,
        help="仅 candidates/pipeline 使用，限制扫描股票数量，便于快速验证。",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    steps_to_run = PIPELINE if args.command == "pipeline" else [args.command]

    print(f"A股隔日T选股系统 v{PRODUCT_VERSION}")
    print(f"运行时间：{now_text()}")
    print(f"执行命令：{args.command}")

    steps = []
    outputs = []

    for command_name in steps_to_run:
        print(f"\n开始执行：{command_name} - {COMMANDS[command_name]['description']}")
        result = call_runner(command_name, max_count=args.max_count)
        steps.append(result)
        outputs.extend(result.get("outputs", []))

        if result["success"]:
            print(f"完成：{command_name}")
        else:
            print(f"失败：{command_name}，原因：{result.get('error', '')}")
            break

    write_run_manifest(
        command=args.command,
        steps=steps,
        outputs=sorted(set(outputs)),
        config_summary={"max_count": args.max_count},
    )

    print(f"\n运行记录已生成：{Path('output/run_manifest.json')}")

    return 0 if all(step["success"] for step in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
