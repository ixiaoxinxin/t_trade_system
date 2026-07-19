# v2.5 数据集质量报告

生成时间：2026-07-19 15:59:24

## 一、数据库

- 数据库类型：SQLite
- 数据库文件：`data/dataset/trade_dataset.sqlite3`

## 二、表记录数

| 表 | 记录数 |
|---|---:|
| `dataset_samples` | 20 |
| `feature_snapshot` | 20 |
| `label_snapshot` | 20 |
| `prediction_log` | 20 |
| `trade_records` | 0 |
| `llm_label_snapshot` | 0 |
| `api_usage_log` | 1 |

## 三、LLM 辅助标签

- 当前开关：关闭
- 未配置或关闭时，不阻断样本、特征、标签、交易记录生成。

## 四、时间序列切分

- 切分文件：`data/dataset/splits/latest.json`

## 五、导出文件

- `data/dataset/dataset_samples.csv`
- `data/dataset/feature_snapshot.csv`
- `data/dataset/label_snapshot.csv`
- `data/dataset/prediction_log.csv`
- `data/dataset/trade_records.csv`
- `data/dataset/llm_label_snapshot.csv`
- `data/dataset/api_usage_log.csv`
- `data/dataset/splits/latest.json`
- `data/dataset/trade_dataset.sqlite3`
- `output/dataset_quality_report.md`
