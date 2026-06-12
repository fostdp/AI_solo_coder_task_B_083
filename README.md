# 古代医学文献馆藏微环境监测与古籍病害预测系统

> 面向明清时期医籍（《本草纲目》刻本、宫廷医案等共3万册）馆藏的微环境监测、老化预测与病害预警全栈系统。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| 数据采集 | 50台环境传感器（温湿度/光照/VOC/霉菌孢子）+ 20台pH检测仪，MQTT QoS=1每5分钟上报 |
| 时序存储 | ClickHouse MergeTree引擎，TTL 2年，1小时/1天物化视图自动聚合 |
| 核心算法 | **Arrhenius纸张老化动力学**（温度/湿度/pH/VOC四维速率乘法器）、**5菌种霉菌生长模型**（温度×相对湿度×暴露时间响应函数）、虫蛀梯形分布 |
| 热力图 | Canvas伪3D书架（4×4旋转矩阵、深度排序），酸化(蓝)/霉变(绿)/虫蛀(棕)RGB加权混合 |
| 可视化 | D3 v7 渲染近3个月微环境趋势、pH下降预测分区着色带、交叉悬停工具提示 |
| 告警分级 | 黄(pH<6.5 或 霉菌>500CFU/m³) / 橙(pH<6.0 或 光照>50lux) / 红(pH<5.5 或 活性霉菌)，钉钉+邮件双通道推送 |
| 知识图谱 | 基于病害-药材权重映射，推荐芸草/黄柏/樟脑等8种古代防蠹药材，含配伍建议 |
| 模拟器 | 日周期正弦(2.5℃)×年周期(3℃)×高斯噪声，支持高温/高湿/霉菌爆发/pH突降异常事件模拟 |

---

## 目录结构

```
AI_solo_coder_task_A_083/
├── backend/
│   ├── algorithms/          # 核心算法
│   │   ├── paper_aging.py   # Arrhenius纸张老化动力学模型
│   │   └── mold_growth.py   # 5菌种霉菌+虫蛀风险模型
│   ├── api/
│   │   └── routes.py        # 25+ REST端点（含无DB降级dummy数据）
│   ├── services/
│   │   ├── mqtt_consumer.py # MQTT订阅+双Queue解耦+3秒批量刷盘
│   │   ├── alert_service.py # 三级告警+钉钉签名HMAC+SMTP SSL
│   │   └── knowledge_graph.py # 防蠹药方权重打分引擎
│   ├── config.py            # Pydantic Settings全局配置
│   ├── database.py          # ClickHouse连接管理器（断线重连）
│   └── main.py              # FastAPI入口+lifespan生命周期
├── frontend/
│   ├── index.html           # 整体布局（顶栏+侧栏+主区域+Modal）
│   ├── css/style.css        # 深色古铜木主题+玻璃态+响应式
│   └── js/
│       ├── shelf3d.js       # Canvas伪3D书架+病害热力图
│       ├── trends.js        # D3趋势曲线+pH预测带
│       └── app.js           # 主控制器+Modal六大板块
├── scripts/
│   └── sensor_simulator.py  # MQTT传感器模拟器（回填/加速/dry-run）
├── sql/
│   └── init_clickhouse.sql  # 10张表+4个物化视图+预置数据
├── requirements.txt
└── README.md
```

---

## 快速开始

### 1. 环境要求

- Python ≥ 3.10
- ClickHouse ≥ 23.3（推荐Docker单机部署）
- MQTT Broker（推荐 EMQX 或 Mosquitto）
- 现代浏览器（Chrome/Edge ≥ 110）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 初始化ClickHouse

```bash
# 方式一：clickhouse-client
clickhouse-client --port 9000 --multiquery < sql/init_clickhouse.sql

# 方式二：curl HTTP接口
curl -X POST 'http://localhost:8123/' --data-binary @sql/init_clickhouse.sql
```

脚本将自动创建：
- 数据库 `ancient_med_lib`
- 10张业务表（含TTL分区策略）
- 4个物化视图（1小时环境聚合、1天pH聚合、每日告警统计）
- 预置7个书架元数据 + 8种防蠹药材知识图谱

### 4. 配置环境变量（可选）

```bash
# Windows PowerShell
$env:CLICKHOUSE_HOST="localhost"
$env:CLICKHOUSE_PORT="8123"
$env:MQTT_BROKER="localhost"
$env:MQTT_PORT="1883"
$env:DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxx"
$env:DINGTALK_SECRET="SECxxx"
$env:SMTP_HOST="smtp.exmail.qq.com"
$env:SMTP_USER="curator@museum.cn"
$env:SMTP_PASSWORD="your-password"
$env:ALERT_EMAIL_TO="restoration@museum.cn,chief@museum.cn"
```

未配置时系统仍可启动，所有API将自动生成**演示降级数据**（正弦日夜波动+人工酸化位点），不影响前端可视化效果。

### 5. 启动后端服务

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

访问：
- 前端主页：http://localhost:8000/
- Swagger文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 6. 启动MQTT传感器模拟器（可选）

```bash
# 标准模式：5分钟间隔（真实速率）
python scripts/sensor_simulator.py

# 加速模式：10倍速（30秒=5分钟）
python scripts/sensor_simulator.py --speed 10

# 回填模式：补写过去7天历史数据（每条记录独立模拟）
python scripts/sensor_simulator.py --backfill --days 7

# 单次上报并退出
python scripts/sensor_simulator.py --once

# dry-run：只打印不发送
python scripts/sensor_simulator.py --dry-run
```

模拟器会周期性制造**异常事件**（高温/高湿/霉菌爆发/pH突降）用于触发告警验证。

---

## 核心算法详解

### 纸张老化动力学（Arrhenius方程）

```
k_ph = A · exp(-Ea / (R·T)) × f_humidity × f_pH × f_VOC
```

- 温度敏感性：Ea=100 kJ/mol，参考温度T_ref=25℃
- 湿度敏感性：f(RH) = 1 + 0.05·ΔRH/10 + 0.02·(ΔRH/10)²
- pH敏感性：f(pH) = 1 + 2.3·(7.0-pH)（酸化自催化）
- VOC敏感性：×(1+0.15·voc_ppm)
- 输出：当前pH→30/90/180/365天pH预测、DP聚合度、剩余寿命（按DP<200判报废）

### 霉菌5菌种模型

| 菌种 | T_min | T_opt | T_max | RH_min | 典型风险场景 |
|------|-------|-------|-------|--------|-------------|
| 黄曲霉 | 10℃ | 33℃ | 48℃ | 82% | 高温高湿夏季 |
| 黑曲霉 | 8℃ | 37℃ | 47℃ | 85% | 温暖封闭角落 |
| 产黄青霉 | 5℃ | 25℃ | 38℃ | 80% | 春秋阴凉处 |
| 球毛壳霉 | 15℃ | 30℃ | 42℃ | 92% | 地下室水渍 |
| 绿色木霉 | 10℃ | 28℃ | 38℃ | 93% | 通风不良书库 |

响应函数：上升段sin(π·x/2)、下降段sin(π·(1-y)/2)；综合风险 = Σ(species_i × w_i × 暴露时间^0.33)

### 告警冷却去重

- 红色告警：30分钟内同(shelf, slot, type)去重
- 橙色告警：60分钟冷却
- 黄色告警：120分钟冷却

钉钉推送使用HMAC-SHA256签名（官方规范），邮件通过SMTP_SSL发送HTML富文本。

---

## 前端交互说明

1. **楼层切换**：左侧栏 1F~3F 切换书架集合
2. **书架选择**：点击卡片列表切换主视图Canvas
3. **图层控制**：酸化/霉变/虫蛀三通道可独立开关，热力图实时混合
4. **三维旋转**：主区域按住鼠标拖拽，X/Y双轴欧拉角变换
5. **格口点击**：弹出Modal六大板块
   - 藏书信息（书名/朝代/责任者/册数）
   - 实时微环境（5大指标卡片）
   - 三维风险条（3病害归一化评分）
   - Arrhenius老化预测（90天pH曲线+分区着色带）
   - D3近3个月微环境趋势（crosshair悬停）
   - 防蠹药方推荐卡片（匹配医籍原文出处）
6. **告警列表**：侧栏实时刷新，点击跳转到对应书架格口

---

## 关键REST端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（含MQTT/ClickHouse连接状态） |
| GET | `/shelves` | 获取书架元数据列表 |
| GET | `/shelves/{id}/slots` | 获取指定书架所有格口藏书 |
| GET | `/env/latest?shelf_id=SH-A-01` | 某书架最新环境快照 |
| GET | `/env/trend?slot_id=SH-A-01-03-02&hours=2160` | 近N小时环境趋势（自动5min/1h/1d颗粒度） |
| GET | `/ph/trend?slot_id=...&days=90` | pH检测历史+预测曲线 |
| **GET** | **`/heatmap?shelf_id=SH-A-01`** | **核心端点：返回所有格口的风险评分+病害预测** |
| POST | `/predict/paper-aging` | 独立调用Arrhenius模型 |
| GET | `/predict/mold?shelf_id=...` | 独立调用霉菌模型 |
| GET | `/alerts?level=RED,ORANGE&limit=50` | 告警查询 |
| POST | `/alerts/{id}/acknowledge` | 告警确认/销项 |
| GET | `/alerts/stats` | 告警分级统计 |
| POST | `/herbs/recommend` | 病害→药材推荐 |
| GET | `/herbs/graph` | 知识图谱节点/边 |
| GET | `/overview/stats` | 顶部仪表盘聚合指标 |

---

## 常见问题

**Q: 没有安装ClickHouse/MQTT能跑起来吗？**
A: 可以。所有API端点内置`_generate_dummy_*()`降级函数，会生成符合日夜周期+酸化位点的演示数据，前端可视化完全可用。

**Q: 如何接入真实硬件？**
A: 传感器发布到两个MQTT Topic即可：
- `ancient_med/sensor/env/{sensor_id}` → JSON：`{timestamp,shelf_id,slot_id,temperature,rh,light,voc,mold_spores}`
- `ancient_med/sensor/ph/{ph_meter_id}` → JSON：`{timestamp,shelf_id,slot_id,ph_value,temperature}`
QoS=1即可，后端自动批量写入和告警触发。

**Q: 如何自定义告警阈值？**
A: 修改`backend/config.py`中的`alert_threshold_*`字段，或通过环境变量（全大写+前缀）注入。

**Q: 如何扩展药材知识图谱？**
A: 两种方式：①在`init_clickhouse.sql`的`INSERT INTO herb_knowledge_graph`追加数据；②直接修改`knowledge_graph.py`中的`FALLBACK_HERBS`与`DISEASE_HERB_MAPPING`权重。

---

## 许可证

仅限历史医学文献馆藏内部使用。
