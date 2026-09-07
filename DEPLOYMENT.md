# 实盘工作台线上部署

## 推荐部署方式

当前系统是 Streamlit + Python 服务，线上推荐使用 Render Docker Web Service。

部署后容器会同时启动：

- `streamlit run app.py`：提供 iPad 可访问的实盘工作台页面。
- `python scheduled_refresh.py --daemon`：按北京时间自动刷新行情、开盘区间、卖点、午盘验证和收盘复盘。

## 必填环境变量

在 Render 的 Environment 中配置：

- `TZ=Asia/Shanghai`
- `DEEPSEEK_API_KEY`：DS 分析用。
- `PUSHPLUS_TOKEN`：手机推送用。

## 自动刷新时间

后台按北京时间执行：

- `09:25` 集合竞价开盘区间刷新
- `09:33` 开盘第一轮 T 区间刷新
- `09:39` 开盘计划刷新
- `09:40` 开盘第二轮 T 区间刷新
- `10:00` 早盘确认 T 区间刷新
- `10:50` 午前风控 T 区间刷新
- `13:30` 午后开盘 T 区间刷新
- `14:00` 午后动态刷新
- `14:30` 尾盘前动态刷新
- `15:00` 收盘复盘刷新

## iPad 使用

部署成功后，直接用 iPad Safari 打开 Render 提供的 `https://...onrender.com` 地址。
页面已经加入窄屏适配，表格在移动端横向滚动，按钮保持可点击高度。
