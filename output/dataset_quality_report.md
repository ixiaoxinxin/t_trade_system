# v2.5 数据集质量报告

生成时间：2026-07-19 17:58:48

## 一、数据库

- 数据库类型：SQLite
- 数据库文件：`data/dataset/trade_dataset.sqlite3`

## 二、表记录数

| 表 | 记录数 |
|---|---:|
| `dataset_samples` | 18 |
| `feature_snapshot` | 18 |
| `label_snapshot` | 18 |
| `prediction_log` | 18 |
| `trade_records` | 0 |
| `llm_label_snapshot` | 3 |
| `llm_provider_status` | 4 |
| `api_usage_log` | 4 |
| `label_review_queue` | 5 |

## 三、标签质量

- 样本数：18
- 标签数：18
- 样本标签匹配数：18
- 标签覆盖率：100.0%
- 缺标签样本数：0

| 字段 | 缺失数 |
|---|---:|
| `direction_up_close` | 0 |
| `touch_buy_range` | 0 |
| `hit_1pct_after_touch` | 0 |
| `hit_2pct_after_touch` | 0 |
| `stop_2pct_after_touch` | 0 |
| `first_event` | 0 |
| `execution_quality` | 0 |

## 四、特征覆盖率

| 字段 | 有值数 | 缺失数 | 覆盖率 |
|---|---:|---:|---:|
| `ret_1d` | 18 | 0 | 100.0% |
| `ret_3d` | 18 | 0 | 100.0% |
| `ret_5d` | 18 | 0 | 100.0% |
| `ret_20d` | 18 | 0 | 100.0% |
| `ma5_gap` | 18 | 0 | 100.0% |
| `ma10_gap` | 18 | 0 | 100.0% |
| `ma20_gap` | 18 | 0 | 100.0% |
| `atr_14` | 18 | 0 | 100.0% |
| `hist_vol_20` | 18 | 0 | 100.0% |
| `amount` | 18 | 0 | 100.0% |
| `avg_amount_5d` | 18 | 0 | 100.0% |
| `volume_ratio` | 18 | 0 | 100.0% |
| `body_pct` | 18 | 0 | 100.0% |
| `upper_shadow_pct` | 18 | 0 | 100.0% |
| `lower_shadow_pct` | 18 | 0 | 100.0% |
| `gap_open_pct` | 18 | 0 | 100.0% |
| `open_strength` | 18 | 0 | 100.0% |
| `first_15m_return` | 18 | 0 | 100.0% |
| `first_15m_drawdown` | 18 | 0 | 100.0% |
| `vwap_gap` | 18 | 0 | 100.0% |
| `sector_rank_1d` | 18 | 0 | 100.0% |
| `sector_rank_5d` | 18 | 0 | 100.0% |
| `sector_breadth` | 18 | 0 | 100.0% |
| `sector_leader_pct` | 18 | 0 | 100.0% |

## 五、人工复核队列

- 待复核数量：5
- 队列表：`label_review_queue`
- 队列报告：`output/label_review_queue.md`

## 六、LLM 辅助标签

- 当前开关：开启
- 估算成本：0.004479 CNY
- 未配置或关闭时，不阻断样本、特征、标签、交易记录生成。

| 供应商 | 模型 | API Key 环境变量 | 是否已配置 | 状态 |
|---|---|---|---:|---|
| deepseek | `deepseek-chat` | `DEEPSEEK_API_KEY` | 1 | ready |
| doubao | `doubao-seed-1-6` | `DOUBAO_API_KEY` | 0 | missing_api_key |
| qwen | `qwen-plus` | `DASHSCOPE_API_KEY` | 0 | missing_api_key |
| glm | `glm-4-flash` | `ZHIPUAI_API_KEY` | 0 | missing_api_key |

## 七、时间序列切分

- 切分文件：`data/dataset/splits/latest.json`

## 八、导出文件

- `data/dataset/splits/latest.json`
- `data/dataset/trade_dataset.sqlite3`
- `output/dataset_quality_report.md`
- `output/label_review_queue.md`
