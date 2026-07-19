# v2.5 训练数据集与标签系统需求文档

更新日期：2026-07-19

## 1. 目标

v2.5 的目标是建立机器学习前的数据地基，把每天的候选、交易计划、市场环境、板块状态、执行结果和次日验证沉淀成可训练、可追溯、可复盘的数据集。

这一版本不直接追求模型收益，而是先解决三个问题：

- 样本是否完整：每一条预测都能回到当时的输入、规则版本、配置和输出。
- 标签是否准确：标签必须围绕真实可执行买点，而不是只看次日最高价。
- 数据是否可训练：特征、标签、切分和版本管理必须能支持 v2.6 方向模型、v2.7 概率模型和 v2.9 预测回顾。

## 2. 范围

### 2.1 本版本必须完成

- 建立样本主表。
- 建立特征快照表。
- 建立标签表。
- 建立预测日志表。
- 建立真实交易记录表，记录用户每一笔日内T、隔日T和复盘补录交易。
- 建立数据集生成脚本。
- 建立时间序列训练、验证、测试切分。
- 建立标签质量检查报告。
- 接入大模型 API 作为辅助标签计算和质检工具。
- 建立 API 供应商配置、成本统计和回退机制。

### 2.2 本版本不做

- 不训练正式生产模型。
- 不输出最终买卖概率。
- 不把大模型判断作为唯一标签来源。
- 不自动下单。

## 3. 数据资产设计

### 3.1 样本主表 `dataset_samples`

一行代表一次“在某个交易日对某只股票形成预测/计划”的样本。

必需字段：

| 字段 | 含义 |
|---|---|
| `sample_id` | 样本唯一 ID，建议 `股票代码_预测日期_规则版本` |
| `stock_code` | 股票代码 |
| `stock_name` | 股票名称 |
| `predict_date` | 预测日期 |
| `feature_date` | 特征截止日期 |
| `target_date` | 验证日期，通常为下一交易日 |
| `rule_version` | 规则系统版本，例如 `v2.4` |
| `config_hash` | 配置摘要 hash |
| `run_id` | 对应 `run_manifest.json` 的运行 ID |
| `source_files` | 使用的输入文件列表 |
| `data_status` | `ready`、`missing_feature`、`missing_label`、`invalid` |

### 3.2 特征快照表 `feature_snapshot`

特征必须保留预测当时能看到的数据，不允许引用未来数据。

字段分组：

| 分组 | 字段 |
|---|---|
| 日线收益 | `ret_1d`、`ret_3d`、`ret_5d`、`ret_20d` |
| 动量 | `ma5_gap`、`ma10_gap`、`ma20_gap`、`ma5_slope`、`ma10_slope` |
| 波动 | `atr_14`、`hist_vol_20`、`range_5d` |
| 成交 | `amount`、`avg_amount_5d`、`turnover_rate`、`volume_ratio` |
| K线 | `body_pct`、`upper_shadow_pct`、`lower_shadow_pct`、`gap_open_pct` |
| 分时 | `open_strength`、`first_15m_return`、`first_15m_drawdown`、`vwap_gap` |
| 路径 | `path_rebound`、`path_fade`、`path_break_morning_high` |
| 市场 | `market_regime`、`market_risk_level`、`market_atr`、`panic_score` |
| 板块 | `sector_name`、`sector_status`、`sector_rank_1d`、`sector_rank_5d`、`sector_breadth`、`sector_leader_pct` |
| 规则 | `candidate_score`、`tail_score`、`final_score`、`overnight_grade`、`risk_level` |

### 3.3 标签表 `label_snapshot`

标签要围绕“是否可执行”定义。

| 标签 | 类型 | 计算口径 |
|---|---|---|
| `direction_up_close` | 0/1 | 次日收盘价是否高于预测日收盘价 |
| `touch_buy_range` | 0/1 | 次日最低价或分时价格是否触达计划低吸区间 |
| `hit_1pct_after_touch` | 0/1 | 触达低吸区间后，是否达到买入价 +1% |
| `hit_2pct_after_touch` | 0/1 | 触达低吸区间后，是否达到买入价 +2% |
| `stop_2pct_after_touch` | 0/1 | 触达低吸区间后，是否先触发买入价 -2% |
| `first_event` | 枚举 | `hit_1pct`、`hit_2pct`、`stop_loss`、`no_event`、`no_touch` |
| `next_day_high_pct` | 数值 | 次日最高价相对预测日收盘价涨幅 |
| `next_day_low_pct` | 数值 | 次日最低价相对预测日收盘价跌幅 |
| `realized_path_type` | 枚举 | `高开高走`、`冲高回落`、`探底回升`、`弱势震荡`、`强势横盘` |
| `execution_quality` | 枚举 | `可执行盈利`、`可执行止损`、`未触达`、`高开无法低吸`、`数据不足` |

### 3.4 真实交易记录表 `trade_records`

真实交易记录是个性化模型的重要输入，用来区分“系统理论上可交易”和“用户真实执行后的结果”。该表由页面手动录入，保存到 `output/trade_records.csv`，后续 v2.5 数据集生成时并入样本库。

必需字段：

| 字段 | 含义 |
|---|---|
| `记录ID` | 单笔记录唯一 ID |
| `记录时间` | 录入系统的时间 |
| `交易日期` | 实际交易日期 |
| `交易类型` | `日内T`、`隔日T`、`建仓`、`减仓`、`清仓`、`观察记录` |
| `股票代码` | 股票代码 |
| `股票名称` | 股票名称 |
| `方向` | `买入`、`卖出`、`买入并卖出`、`补仓`、`减仓` |
| `买入价格` | 实际买入价格 |
| `卖出价格` | 实际卖出价格，未卖出时允许为空 |
| `数量` | 成交股数 |
| `费用` | 手续费、印花税等合计 |
| `盈亏金额` | 已卖出时自动计算 |
| `收益率` | 已卖出时自动计算 |
| `持仓状态` | `持仓中` 或 `已卖出` |
| `策略来源` | `系统候选`、`手动观察`、`盘中机会`、`复盘补录` |
| `是否按计划执行` | `是`、`否`、`部分执行`、`未记录` |
| `情绪状态` | `冷静`、`犹豫`、`追高`、`恐慌`、`贪心`、`未记录` |
| `备注` | 买入理由、卖出理由、错过点、执行偏差 |

页面要求：

- 在 Streamlit 页面新增 `交易记录` Tab。
- 表单必须简洁，支持 30 秒内完成一笔记录。
- 卖出价允许为空，用于先记录持仓。
- 保存后立即写入 `output/trade_records.csv` 并刷新表格。
- 页面展示最近 30 条记录、持仓中数量、已实现盈亏和平均收益率。

建模用途：

- 作为个人执行样本，训练“我更容易在哪类形态中赚/亏”的个性化特征。
- 与系统候选样本关联，区分 `系统建议`、`实际执行`、`执行偏差`。
- 用于 v2.7 后的个性化概率校准，例如同样 A 级票，在用户真实执行中达到 1% 的概率。
- 用于分析情绪标签和收益之间的关系，后续给出执行纪律提示。

## 4. 大模型 API 辅助标签系统

### 4.1 使用原则

大模型只做辅助，不替代确定性行情计算。

优先级：

1. 确定性数值计算：OHLC、分时价格、计划买入区间、止损价。
2. 规则标签：触达、先止损、达到 1%/2%、收盘涨跌。
3. 大模型辅助：复杂路径解释、异常样本质检、标签冲突解释、人工复核提示。

### 4.2 大模型适合处理的任务

- 根据分时摘要判断 `realized_path_type`。
- 对规则标签冲突给出解释，例如“最低价触达但成交区间极短，是否应标为弱可执行”。
- 对异常数据生成质检意见，例如价格缺失、分时断点、涨跌停导致不可执行。
- 生成样本备注，帮助后续人工复盘。
- 对特征和标签做一致性检查，例如 `touch_buy_range=0` 时不应出现 `hit_1pct_after_touch=1`。

### 4.3 大模型不应处理的任务

- 不直接决定涨跌标签。
- 不直接修改价格、收益率、ATR、成交额等数值特征。
- 不根据股票名称推断行业或概念。
- 不输出买入、卖出、仓位等交易指令。

### 4.4 输入与输出格式

输入给大模型的内容必须是脱敏、结构化摘要：

```json
{
  "sample_id": "002378_2026-07-19_v2.4",
  "stock_code": "002378",
  "predict_date": "2026-07-19",
  "target_date": "2026-07-20",
  "plan": {
    "buy_range_low": 39.71,
    "buy_range_high": 40.11,
    "stop_loss": 38.90,
    "overnight_grade": "A"
  },
  "next_day_market": {
    "open": 40.30,
    "high": 41.00,
    "low": 39.80,
    "close": 40.60,
    "minute_path_summary": "开盘冲高后回落，10:20触达低吸区间，午后回升"
  },
  "rule_labels": {
    "touch_buy_range": 1,
    "hit_1pct_after_touch": 1,
    "stop_2pct_after_touch": 0
  }
}
```

输出必须是严格 JSON：

```json
{
  "realized_path_type": "探底回升",
  "execution_quality": "可执行盈利",
  "label_confidence": 0.86,
  "needs_manual_review": false,
  "conflict_fields": [],
  "reason": "10:20后触达低吸区间，随后反弹达到1%目标，未先触发止损。"
}
```

### 4.5 标签融合规则

- 大模型输出 `label_confidence < 0.70`：只记录备注，不更新辅助标签。
- 大模型与规则标签冲突：写入 `label_review_queue.csv`，等待人工确认。
- 大模型只允许更新 `realized_path_type`、`execution_quality`、`llm_reason`、`needs_manual_review`。
- 所有大模型结果必须记录 `provider`、`model`、`prompt_version`、`input_tokens`、`output_tokens`、`cost_estimate`。

## 5. 国产大模型 API 价格对比

说明：以下价格为 2026-07-19 查询公开文档得到的快照，模型服务价格变化很快，正式开发前必须重新核对。单位统一换算为“每百万 tokens”，未含税和优惠券。

| 供应商 | 推荐用途 | 代表模型 | 输入价格 | 输出价格 | 备注 |
|---|---|---|---|---|---|
| DeepSeek | 低成本批量标签解释、规则冲突说明 | `deepseek-chat` | $0.27，缓存命中 $0.07 | $1.10 | 性价比优先；reasoner 为 $0.55/$2.19 |
| 阿里云百炼 / 通义千问 | 通用中文理解、企业稳定性 | `qwen-max` | 2.4 元 | 9.6 元 | `qwen3-max` 标价 12/36 元，有限时折扣 |
| 火山方舟 / 豆包 | 中文场景、低价长上下文、后续 Agent 能力 | `doubao-seed-1.8` | 0.8 元起 | 2 元起，长输出档更高 | `Doubao-Seed-2.1-pro` 约 6/30 元 |
| 智谱 GLM | 结构化解释、国产可选备份 | `GLM-4.5-Air` | 0.8 元 | 2 元 | 高阶 `GLM-5.2` 为 8/28 元 |
| 百度千帆 / 文心 | 百度生态、批量推理和国产备份 | `ERNIE-4.5-Turbo` | 0.8 元 | 3.2 元 | `ERNIE 5.1` 为 4/18 元 |
| Moonshot / Kimi | 长上下文复盘、文档读取 | `moonshot-v1-8k` | $0.20 | $2.00 | 32k/128k 价格更高，适合长文本 |
| 腾讯混元 | 腾讯云生态备份 | `Hy-MT2-Lite` | 0.3 元 | 1.2 元 | 价格来自腾讯云公开计费页，接入前需确认接口适配 |

价格来源：

- DeepSeek API Pricing: https://api-docs.deepseek.com/quick_start/pricing-details-usd
- 阿里云百炼模型价格: https://help.aliyun.com/en/model-studio/model-pricing
- 火山方舟价格页: https://www.volcengine.com/product/ark
- 火山方舟模型服务计费说明: https://www.volcengine.com/docs/6581/2389072?lang=zh
- 智谱开放平台价格: https://bigmodel.cn/pricing
- 百度千帆价格: https://cloud.baidu.com/doc/qianfan-docs/s/Jm8r1826a
- Kimi API Pricing: https://platform.kimi.ai/docs/pricing/chat-v1
- 腾讯云 Token 计费标准: https://buy.cloud.tencent.com/price/tcb/overview

### 5.1 推荐接入顺序

第一优先级：

- DeepSeek：批量成本低，适合大量样本的标签解释和质检。
- 豆包 / 火山方舟：国产生态和价格有优势，适合作为主备模型。
- 通义千问 / 阿里云百炼：企业稳定性好，适合作为高质量复核模型。

第二优先级：

- 智谱 GLM：结构化输出稳定时可作为备份。
- 百度千帆：如果后续接入百度云生态，可作为备份。
- Kimi：用于长上下文复盘和文档摘要，不作为默认批量标注模型。

## 6. 配置需求

新增 `config.yaml` 配置建议：

```yaml
llm_labeling:
  enabled: false
  provider_priority:
    - deepseek
    - doubao
    - qwen
    - glm
  max_daily_cost_cny: 20
  min_confidence: 0.70
  review_on_conflict: true
  prompt_version: v2.5-labeling-001
  providers:
    deepseek:
      base_url: https://api.deepseek.com
      api_key_env: DEEPSEEK_API_KEY
      model: deepseek-chat
    doubao:
      base_url: https://ark.cn-beijing.volces.com/api/v3
      api_key_env: ARK_API_KEY
      model: doubao-seed-1-8
    qwen:
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      api_key_env: DASHSCOPE_API_KEY
      model: qwen-max
    glm:
      base_url: https://open.bigmodel.cn/api/paas/v4
      api_key_env: ZHIPU_API_KEY
      model: glm-4.5-air
```

要求：

- API Key 只允许来自环境变量或本地私密配置。
- 未配置 API Key 时，数据集生成仍可运行，只跳过大模型辅助标签。
- 每次调用都记录 token、费用估算、模型和 prompt 版本。
- 达到日预算上限时自动停止大模型调用。

## 7. 开发计划

### M1 样本库基础

任务：

- 新增 `dataset_builder.py`。
- 读取 `output/final_watchlist.csv`、`output/daily_plan.md`、`output/market_environment.json`、`output/run_manifest.json`、`output/trade_records.csv`。
- 生成 `data/dataset/samples.csv`。
- 生成 `data/dataset/feature_snapshot.csv`。

验收：

- 可以为现有输出生成样本主表。
- 样本包含 `sample_id`、预测日期、目标日期、规则版本、配置摘要。

### M1.5 真实交易记录入口

任务：

- 新增 `trade_journal.py`。
- 在 Streamlit 页面新增 `交易记录` Tab。
- 支持手动记录日内T、隔日T、建仓、减仓、清仓和复盘补录。
- 自动计算已卖出记录的盈亏金额和收益率。
- 将记录保存为 `output/trade_records.csv`。

验收：

- 页面可以手动新增一笔交易记录。
- 未填写卖出价时，记录状态为 `持仓中`。
- 填写卖出价时，自动计算盈亏金额和收益率。
- 记录可被 `load_trade_records` 稳定读取，后续数据集生成可直接使用。

### M2 标签计算

任务：

- 新增 `label_calculator.py`。
- 读取次日 OHLC 和分时数据。
- 计算 `touch_buy_range`、`hit_1pct_after_touch`、`hit_2pct_after_touch`、`stop_2pct_after_touch`、`first_event`。
- 输出 `data/dataset/label_snapshot.csv`。

验收：

- 标签字段无缺失。
- 标签逻辑可用小样本人工复核。
- 无未来函数。

### M3 大模型辅助标签

任务：

- 新增 `llm_labeler.py`。
- 新增 `prompts/labeling_v2.5.md`。
- 支持 OpenAI-compatible API 客户端。
- 支持 DeepSeek、豆包、通义、智谱的 provider 配置。
- 输出 `data/dataset/llm_label_snapshot.csv` 和 `data/dataset/label_review_queue.csv`。

验收：

- 未配置 API Key 时不会阻断数据集生成。
- 配置 API Key 后可对小样本生成结构化 JSON 辅助标签。
- 冲突样本进入人工复核队列。

### M4 数据质量报告

任务：

- 新增 `dataset_quality_report.py`。
- 统计样本数量、标签覆盖率、缺失字段、冲突样本、LLM 成本。
- 输出 `output/dataset_quality_report.md`。

验收：

- 能看到样本数、有效标签数、需人工复核数、成本估算。
- 能定位缺数据原因。

### M5 时间序列切分

任务：

- 新增 `dataset_splitter.py`。
- 支持滚动切分：训练 2 年、验证 3 个月、测试 1 个月。
- 输出 `data/dataset/splits/*.json`。

验收：

- 切分不打乱时间。
- 每个 split 有明确日期范围和样本数量。

## 8. 验收标准

- `python main.py dataset` 可生成样本、特征、标签和质量报告。
- `data/dataset/samples.csv`、`feature_snapshot.csv`、`label_snapshot.csv` 存在。
- `output/trade_records.csv` 可记录真实交易，并作为个性化样本输入。
- 标签计算可在无大模型 API Key 时完成。
- 大模型辅助标签可配置开启，并支持成本上限。
- `label_review_queue.csv` 能收集冲突和低置信样本。
- 质量报告能说明样本覆盖率、缺失率、冲突率和 LLM 调用成本。
- v2.6 可以直接读取 v2.5 数据集训练方向模型。

## 9. 风险与控制

| 风险 | 控制 |
|---|---|
| 行情源缺分时数据 | 先用日线标签，分时标签标记为缺失 |
| 大模型输出不稳定 | 强制 JSON schema，低置信进入复核队列 |
| API 费用失控 | 设置 `max_daily_cost_cny` 和调用数量上限 |
| 未来函数 | 特征表只允许读取 `feature_date` 及以前数据 |
| 标签口径漂移 | 所有标签函数和 prompt 必须版本化 |
| 模型供应商价格变化 | 每次正式接入前复核价格并更新文档 |

## 10. 后续衔接

- v2.6 使用 `direction_up_close` 训练次日涨跌分类模型。
- v2.7 使用 `hit_1pct_after_touch`、`hit_2pct_after_touch`、`stop_2pct_after_touch` 训练概率模型。
- v2.8 使用特征贡献和 LLM 解释字段增强可解释性。
- v2.9 使用预测日志和标签结果做模型评分与版本对比。
