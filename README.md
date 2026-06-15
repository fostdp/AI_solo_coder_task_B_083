# 古代医学文献馆藏微环境监测与古籍病害预测系统

## 项目概述

基于物联网和AI算法的古籍保护监测系统，用于历史医学文献博物馆的古籍微环境监测和病害预测。

## 系统架构

```
前端 (Canvas + D3.js)
    ↓ HTTP/WebSocket
后端 (FastAPI)
    ↓ MQTT订阅
传感器 (50台环境传感器 + 20台pH检测仪)
    ↓ 时序数据存储
ClickHouse数据库
```

## 目录结构

```
├── backend/                    # 后端代码
│   ├── app/
│   │   ├── algorithms/         # 核心算法
│   │   │   ├── arrhenius.py    # 纸张老化动力学模型
│   │   │   └── mold_growth.py  # 霉菌生长模型
│   │   ├── alerts/             # 告警系统
│   │   ├── knowledge/          # 知识图谱
│   │   ├── routers/            # API路由
│   │   ├── config.py           # 配置管理
│   │   ├── database.py         # ClickHouse数据库
│   │   ├── mqtt_subscriber.py  # MQTT订阅服务
│   │   └── main.py             # 应用入口
│   ├── simulator/
│   │   └── sensor_simulator.py # 传感器模拟器
│   ├── requirements.txt        # Python依赖
│   ├── run.py                  # 启动脚本
│   └── .env.example            # 环境变量示例
├── clickhouse/
│   └── init.sql                # 数据库初始化脚本
├── frontend/                   # 前端代码
│   ├── index.html              # 主页面
│   ├── css/
│   │   └── style.css           # 样式
│   └── js/
│       ├── shelf3d.js          # Canvas三维书架
│       ├── heatmap.js          # 热力图管理
│       ├── trendChart.js       # D3.js趋势图
│       └── app.js              # 主应用
```

## 核心功能

### 1. 微环境监测
- 50台环境传感器（温湿度、光照、VOC、霉菌孢子浓度）
- 20台纸张pH值检测仪
- 每5分钟通过MQTT协议上报数据
- ClickHouse时序数据存储

### 2. 核心算法
- **纸张老化动力学模型**：基于Arrhenius方程，计算pH下降速率和老化指数
- **霉菌生长模型**：基于温度和相对湿度的响应函数，预测霉菌生长风险

### 3. 告警系统
- **黄色告警**：pH<6.5 或 霉菌孢子>500 CFU/m³
- **橙色告警**：pH<6.0 或 光照>50 lux
- **红色告警**：pH<5.5 或 检测到活性霉菌
- 推送方式：钉钉机器人、邮件

### 4. 三维可视化
- Canvas绘制三维书架模型
- 病害区域热力图标注（酸化、霉变、虫蛀）
- 点击格口查看近3个月微环境趋势
- 纸张老化速率预测曲线

### 5. 知识图谱
- 古代防蠹药方推荐（芸草、黄柏等）
- 病害与古籍关联
- 传统防治方法查询

## 快速开始

### 1. 数据库初始化
```bash
clickhouse-client --multiquery < clickhouse/init.sql
```

### 2. 后端启动
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 配置文件
python run.py
```

### 3. 传感器模拟器
```bash
cd backend
python -m simulator.sensor_simulator --broker localhost --port 1883
```

### 4. 前端访问
直接打开 `frontend/index.html` 或使用静态文件服务器：
```bash
cd frontend
python -m http.server 8080
```

## API文档

启动后端后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 核心算法说明

### Arrhenius纸张老化模型
```
k = A * exp(-Ea / (R * T))
pH(t) = pH0 - k*t
```
考虑温度、湿度和自催化效应，预测纸张pH值变化趋势。

### 霉菌生长模型
基于温度响应函数（钟形曲线）和湿度响应函数（S型曲线），计算霉菌生长速率和孢子浓度预测。

## 告警分级

| 级别 | pH阈值 | 霉菌孢子 | 光照 | 推送方式 |
|------|--------|----------|------|----------|
| 黄 | <6.5 | >500 CFU/m³ | - | 钉钉提醒 |
| 橙 | <6.0 | - | >50 lux | 钉钉+邮件 |
| 红 | <5.5 | 活性霉菌 | - | 钉钉@所有人+邮件 |

## 病害知识图谱

- **酸化**：黄柏染纸法、石灰水脱酸法
- **霉变**：芸香避蠹法、苍术熏库法
- **虫蛀**：芸草藏书法、雄黄熏书法、苦楝纸法
- **光老化**：槐花染纸防光法、五倍子固色法
- **潮湿**：石灰除湿法、木炭吸潮法
