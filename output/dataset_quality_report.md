# v2.5 数据集质量报告

生成时间：2026-07-19 16:33:23

## 一、数据库

- 数据库类型：SQLite
- 数据库文件：`data/dataset/trade_dataset.sqlite3`

## 二、表记录数

| 表 | 记录数 |
|---|---:|
| `dataset_samples` | 40 |
| `feature_snapshot` | 40 |
| `label_snapshot` | 20 |
| `prediction_log` | 20 |
| `trade_records` | 0 |
| `llm_label_snapshot` | 0 |
| `api_usage_log` | 1 |
| `label_review_queue` | 8 |

## 三、标签质量

- 样本数：40
- 标签数：20
- 样本标签匹配数：20
- 标签覆盖率：50.0%
- 缺标签样本数：20

| 字段 | 缺失数 |
|---|---:|
| `direction_up_close` | 0 |
| `touch_buy_range` | 0 |
| `hit_1pct_after_touch` | 0 |
| `hit_2pct_after_touch` | 0 |
| `stop_2pct_after_touch` | 0 |
| `first_event` | 0 |
| `execution_quality` | 0 |

## 四、人工复核队列

- 待复核数量：8
- 队列表：`label_review_queue`
- 队列报告：`output/label_review_queue.md`

## 五、LLM 辅助标签

- 当前开关：关闭
- 估算成本：0.0 CNY
- 未配置或关闭时，不阻断样本、特征、标签、交易记录生成。

## 六、时间序列切分

- 切分文件：`data/dataset/splits/latest.json`

## 七、导出文件

- `data/dataset/splits/latest.json`
- `data/dataset/trade_dataset.sqlite3`
- `output/dataset_quality_report.md`
- `output/label_review_queue.md`
