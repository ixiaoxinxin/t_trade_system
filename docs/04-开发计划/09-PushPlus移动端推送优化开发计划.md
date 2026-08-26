# PushPlus移动端推送优化开发计划

## 图谱关系

上游：[PushPlus移动端推送优化需求](../03-需求文档/15-PushPlus移动端推送优化需求.md)
下游：无

## 开发步骤

1. 新增移动端推送模块，封装 PushPlus 发送和 HTML 卡片模板。
2. 卖点信号推送从 Markdown 表格切换为 HTML 卡片。
3. 开盘T区间生成后调用同一 PushPlus 发送能力。
4. 新增单元测试，验证 HTML 包含移动端 viewport 和卡片，不输出 Markdown 表格。
5. 保持本地 Markdown 报告不变，只优化手机推送内容。

## 验证命令

1. `python -m py_compile mobile_push.py sell_signal_engine.py opening_levels.py`
2. `python -m unittest discover -s tests -p 'test_mobile_push.py'`
3. `python -m unittest discover -s tests -p 'test_opening_levels.py'`

## 提交范围

只提交代码、测试和知识库文档，不提交行情缓存、模型文件、SQLite、运行输出。
