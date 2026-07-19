# A股隔日T选股系统

当前产品版本：v2.0

本项目是一个本地运行的 A股隔日T选股、交易计划、卖点信号和复盘辅助系统。系统只做规则化辅助分析，不自动下单，不构成投资建议。

## 安装

建议使用 Python 3.10+。

```bash
pip install -r requirements.txt
```

## 配置

核心参数在 `config.yaml`：

- `capital`：总资金、单票资金、最大交易数量。
- `stock_filter`：价格、成交额、振幅、涨幅、MA5偏离过滤。
- `score_weight`：日线评分和尾盘评分权重。
- `tail_confirm`：尾盘确认阈值。
- `risk`：风险扣分阈值。
- `runtime`：缓存和候选扫描数量。
- `dataset`：SQLite 样本库位置、CSV 导出目录、切分目录。
- `llm_labeling`：大模型辅助标签开关、国产供应商优先级、成本上限和 API Key 环境变量。

PushPlus token 当前沿用既有代码逻辑，可通过环境变量 `PUSHPLUS_TOKEN` 覆盖。

## 命令行运行

查看帮助：

```bash
python main.py --help
```

一键主流程：

```bash
python main.py pipeline
```

快速测试候选扫描：

```bash
python main.py candidates --max-count 20
```

单模块运行：

```bash
python main.py market
python main.py candidates
python main.py tail
python main.py plan
python main.py lunch
python main.py sell
python main.py next-day
python main.py review
python main.py factor-rank
python main.py dataset
python main.py migrate-db
```

每次通过 `main.py` 运行后，会生成：

```text
output/run_manifest.json
```

用于追踪本次运行的步骤、输出文件和失败原因。

## 本地前端

```bash
streamlit run app.py
```

前端提供市场环境、主流程、卖点信号、午盘验证、次日验证和复盘库入口。

## 主要输出

- `output/market_environment.csv`
- `output/market_environment.md`
- `output/market_environment.json`
- `output/overnight_t_candidates.csv`
- `output/final_watchlist.csv`
- `output/final_watchlist.md`
- `output/daily_plan.md`
- `output/lunch_review.csv`
- `output/lunch_review.md`
- `output/sell_signal.csv`
- `output/sell_signal.md`
- `output/next_day_review.csv`
- `output/next_day_review.md`
- `output/factor_performance.csv`
- `output/run_manifest.json`
- `data/dataset/trade_dataset.sqlite3`
- `data/dataset/splits/latest.json`
- `output/dataset_quality_report.md`

v2.5 起，SQLite 是页面和训练数据的主存储。旧 CSV/Markdown/JSON 文件只作为兼容导入或过渡导出，页面读取优先走 `data/dataset/trade_dataset.sqlite3`。

## 常见问题

### 行情接口失败怎么办？

本系统依赖新浪、腾讯、东方财富/AKShare 等公开数据接口。网络异常、接口限流、字段变化都可能导致失败。建议先用：

```bash
python main.py candidates --max-count 5
```

做小规模验证。

### 为什么不再输出板块/热点标签？

v2.0 按当前决策去掉轻量板块识别功能，避免基于股票名称的弱规则误导交易计划。后续如需恢复，应接入更可靠的行业/概念映射。

### 为什么次日验证结果更细了？

v2.0 不再只看“次日最高达到 1% 且未触发 -2%”，而是先判断是否触达计划低吸区间，再区分给买点成功、给买点失败、未给买点、风险触发和数据不足。

### 数据集为什么用 SQLite？

v2.5 默认用 SQLite：免费、轻量、无需启动服务，数据库文件位于 `data/dataset/trade_dataset.sqlite3`。页面输出、报告文档、真实交易记录、日线缓存和分钟缓存都会迁入 SQLite。后续样本量变大后，可从 SQLite 迁移到 DuckDB 或 PostgreSQL。
