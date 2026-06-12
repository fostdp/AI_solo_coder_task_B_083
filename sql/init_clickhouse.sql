-- ============================================================
-- 古代医学文献馆藏微环境监测与古籍病害预测系统
-- ClickHouse 初始化脚本
-- ============================================================

CREATE DATABASE IF NOT EXISTS ancient_med_lib
    COMMENT '古代医学文献馆藏监测数据库'
    ENGINE = Ordinary;

USE ancient_med_lib;

-- ============================================================
-- 1. 书架与馆藏元数据表
-- ============================================================
DROP TABLE IF EXISTS bookshelf_metadata;
CREATE TABLE bookshelf_metadata (
    shelf_id        String COMMENT '书架编号，如SH-A-01',
    shelf_name      String COMMENT '书架名称',
    floor_num       Int32  COMMENT '楼层',
    room_id         String COMMENT '房间号',
    total_slots     Int32  COMMENT '总格口数',
    rows_count      Int32  COMMENT '行数',
    cols_count      Int32  COMMENT '列数',
    location_x      Float64 COMMENT '3D坐标X',
    location_y      Float64 COMMENT '3D坐标Y',
    location_z      Float64 COMMENT '3D坐标Z',
    create_time     DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (shelf_id)
COMMENT '书架元数据表';

DROP TABLE IF EXISTS book_slot_metadata;
CREATE TABLE book_slot_metadata (
    slot_id         String COMMENT '格口编号，如SH-A-01-R02-C03',
    shelf_id        String COMMENT '所属书架',
    row_num         Int32  COMMENT '行号',
    col_num         Int32  COMMENT '列号',
    book_title      String COMMENT '藏书名称',
    book_dynasty    String COMMENT '朝代：明/清',
    book_type       String COMMENT '类型：刻本/医案/手稿',
    book_count      Int32  COMMENT '藏书册数',
    sensor_env_id   String COMMENT '关联环境传感器ID',
    sensor_ph_id    String COMMENT '关联pH传感器ID',
    create_time     DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (slot_id, shelf_id)
COMMENT '格口与藏书元数据表';

-- ============================================================
-- 2. 环境传感器时序数据表 (MergeTree + TTL)
-- ============================================================
DROP TABLE IF EXISTS env_sensor_data;
CREATE TABLE env_sensor_data (
    timestamp       DateTime64(3) COMMENT '采集时间戳(毫秒)',
    sensor_id       String COMMENT '传感器ID ENV-001 ~ ENV-050',
    shelf_id        String COMMENT '所属书架',
    slot_id         String COMMENT '最近格口',
    temperature     Float64 COMMENT '温度(℃) 10~35',
    humidity        Float64 COMMENT '相对湿度(%) 30~70',
    light_lux       Float64 COMMENT '光照(lux) 0~200',
    voc_ppm         Float64 COMMENT 'VOC浓度(ppm) 0~5',
    mold_spores     Float64 COMMENT '霉菌孢子浓度(CFU/m³) 0~2000',
    active_mold     UInt8   COMMENT '是否检测到活性霉菌 0/1',
    rssi            Int16   COMMENT '信号强度'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (sensor_id, timestamp)
TTL timestamp + INTERVAL 2 YEAR
COMMENT '环境传感器时序数据表 (5分钟上报)';

-- ============================================================
-- 3. 纸张pH值检测仪时序数据表
-- ============================================================
DROP TABLE IF EXISTS ph_sensor_data;
CREATE TABLE ph_sensor_data (
    timestamp       DateTime64(3) COMMENT '采集时间戳(毫秒)',
    sensor_id       String COMMENT 'pH传感器ID PH-001 ~ PH-020',
    shelf_id        String COMMENT '所属书架',
    slot_id         String COMMENT '检测格口',
    ph_value        Float64 COMMENT '纸张pH值 4.0~8.0',
    paper_cond      String COMMENT '纸张状况评估',
    rssi            Int16   COMMENT '信号强度'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (sensor_id, timestamp)
TTL timestamp + INTERVAL 2 YEAR
COMMENT '纸张pH值检测时序数据表';

-- ============================================================
-- 4. 告警事件表
-- ============================================================
DROP TABLE IF EXISTS alert_events;
CREATE TABLE alert_events (
    event_id        String COMMENT '告警事件UUID',
    timestamp       DateTime64(3) COMMENT '触发时间',
    alert_level     String COMMENT '告警等级：YELLOW/ORANGE/RED',
    alert_type      String COMMENT '告警类型：ACIDOSIS/MOLD/LIGHT/INSECT',
    shelf_id        String COMMENT '书架',
    slot_id         String COMMENT '格口（可空）',
    sensor_id       String COMMENT '触发传感器',
    trigger_value   Float64 COMMENT '触发值',
    threshold_value Float64 COMMENT '阈值',
    description     String COMMENT '告警描述',
    is_acknowledged UInt8 DEFAULT 0 COMMENT '是否已确认',
    ack_user        String DEFAULT '' COMMENT '确认人',
    ack_time        DateTime64(3) COMMENT '确认时间'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (alert_level, timestamp)
TTL timestamp + INTERVAL 3 YEAR
COMMENT '告警事件表';

-- ============================================================
-- 5. 病害预测结果表
-- ============================================================
DROP TABLE IF EXISTS disease_prediction;
CREATE TABLE disease_prediction (
    predict_time    DateTime64(3) COMMENT '预测时间',
    slot_id         String COMMENT '格口',
    shelf_id        String COMMENT '书架',
    ph_30d          Float64 COMMENT '30天后pH预测值',
    ph_90d          Float64 COMMENT '90天后pH预测值',
    aging_rate      Float64 COMMENT '纸张老化速率(pH/年)',
    mold_risk       Float64 COMMENT '霉菌生长风险指数(0~1)',
    mold_growth_rate Float64 COMMENT '霉菌生长速率',
    insect_risk     Float64 COMMENT '虫蛀风险指数',
    overall_risk    String COMMENT '综合风险等级：LOW/MEDIUM/HIGH/CRITICAL',
    recommend_herbs String COMMENT '推荐防虫药材（逗号分隔）'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(predict_time)
ORDER BY (slot_id, predict_time)
TTL predict_time + INTERVAL 1 YEAR
COMMENT '病害预测结果表';

-- ============================================================
-- 6. 物化视图：环境传感器1小时/1天聚合
-- ============================================================
DROP TABLE IF EXISTS env_sensor_1h_agg;
CREATE TABLE env_sensor_1h_agg (
    hour_start      DateTime COMMENT '小时开始',
    sensor_id       String,
    shelf_id        String,
    slot_id         String,
    temp_avg        Float64 COMMENT '平均温度',
    temp_max        Float64 COMMENT '最高温度',
    temp_min        Float64 COMMENT '最低温度',
    humi_avg        Float64 COMMENT '平均湿度',
    humi_max        Float64,
    humi_min        Float64,
    light_avg       Float64,
    light_max       Float64,
    voc_avg         Float64,
    mold_spores_avg Float64,
    mold_spores_max Float64,
    active_mold_cnt UInt64 COMMENT '活性霉菌检测次数',
    sample_count    UInt64 COMMENT '样本数'
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour_start)
ORDER BY (sensor_id, hour_start)
COMMENT '环境传感器1小时聚合表';

DROP TABLE IF EXISTS env_sensor_1h_mv;
CREATE MATERIALIZED VIEW env_sensor_1h_mv
TO env_sensor_1h_agg
AS SELECT
    toStartOfHour(timestamp)               AS hour_start,
    sensor_id,
    shelf_id,
    slot_id,
    avg(temperature)                       AS temp_avg,
    max(temperature)                       AS temp_max,
    min(temperature)                       AS temp_min,
    avg(humidity)                          AS humi_avg,
    max(humidity)                          AS humi_max,
    min(humidity)                          AS humi_min,
    avg(light_lux)                         AS light_avg,
    max(light_lux)                         AS light_max,
    avg(voc_ppm)                           AS voc_avg,
    avg(mold_spores)                       AS mold_spores_avg,
    max(mold_spores)                       AS mold_spores_max,
    sum(active_mold)                       AS active_mold_cnt,
    count()                                AS sample_count
FROM env_sensor_data
GROUP BY hour_start, sensor_id, shelf_id, slot_id;

-- ============================================================
-- 7. 物化视图：pH传感器1天聚合
-- ============================================================
DROP TABLE IF EXISTS ph_sensor_1d_agg;
CREATE TABLE ph_sensor_1d_agg (
    day_start       Date COMMENT '日期',
    sensor_id       String,
    shelf_id        String,
    slot_id         String,
    ph_avg          Float64 COMMENT '日均pH',
    ph_min          Float64 COMMENT '最低pH',
    ph_max          Float64,
    ph_drop_rate    Float64 COMMENT 'pH下降速率(当日)',
    sample_count    UInt64
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day_start)
ORDER BY (sensor_id, day_start)
COMMENT 'pH传感器1天聚合表';

DROP TABLE IF EXISTS ph_sensor_1d_mv;
CREATE MATERIALIZED VIEW ph_sensor_1d_mv
TO ph_sensor_1d_agg
AS SELECT
    toDate(timestamp)                      AS day_start,
    sensor_id,
    shelf_id,
    slot_id,
    avg(ph_value)                          AS ph_avg,
    min(ph_value)                          AS ph_min,
    max(ph_value)                          AS ph_max,
    max(ph_value) - min(ph_value)          AS ph_drop_rate,
    count()                                AS sample_count
FROM ph_sensor_data
GROUP BY day_start, sensor_id, shelf_id, slot_id;

-- ============================================================
-- 8. 告警统计表（物化视图）
-- ============================================================
DROP TABLE IF EXISTS alert_daily_stats;
CREATE TABLE alert_daily_stats (
    stat_date       Date,
    shelf_id        String,
    alert_level     String,
    alert_type      String,
    alert_count     UInt64
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(stat_date)
ORDER BY (stat_date, shelf_id, alert_level, alert_type);

DROP TABLE IF EXISTS alert_daily_stats_mv;
CREATE MATERIALIZED VIEW alert_daily_stats_mv
TO alert_daily_stats
AS SELECT
    toDate(timestamp) AS stat_date,
    shelf_id,
    alert_level,
    alert_type,
    count()           AS alert_count
FROM alert_events
GROUP BY stat_date, shelf_id, alert_level, alert_type;

-- ============================================================
-- 9. 古代防蠹药方知识图谱表
-- ============================================================
DROP TABLE IF EXISTS herb_knowledge_graph;
CREATE TABLE herb_knowledge_graph (
    herb_id         String COMMENT '药材ID',
    herb_name       String COMMENT '药材名称',
    herb_cn_name    String COMMENT '中文名',
    source_book     String COMMENT '记载医籍',
    source_dynasty  String COMMENT '出处朝代',
    usage_method    String COMMENT '使用方法',
    target_pests    Array(String) COMMENT '防治对象',
    efficacy        String COMMENT '功效描述',
    toxicity_level  String COMMENT '毒性：LOW/MEDIUM/HIGH',
    compatibility   Array(String) COMMENT '配伍药材',
    create_time     DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (herb_id)
COMMENT '古代防蠹药方知识图谱';

-- ============================================================
-- 10. 初始化示例数据：书架与格口
-- ============================================================
INSERT INTO bookshelf_metadata
(shelf_id, shelf_name, floor_num, room_id, total_slots, rows_count, cols_count, location_x, location_y, location_z) VALUES
('SH-A-01', 'A区一号书架-明版本草区', 1, 'RM-101', 48, 6, 8, 0, 0, 0),
('SH-A-02', 'A区二号书架-明版医案区', 1, 'RM-101', 48, 6, 8, 3, 0, 0),
('SH-A-03', 'A区三号书架-明版综合区', 1, 'RM-101', 48, 6, 8, 6, 0, 0),
('SH-B-01', 'B区一号书架-清版本草区', 1, 'RM-102', 48, 6, 8, 0, 0, 3),
('SH-B-02', 'B区二号书架-清版宫廷医案', 1, 'RM-102', 48, 6, 8, 3, 0, 3),
('SH-C-01', 'C区一号书架-珍本手稿区', 2, 'RM-201', 36, 6, 6, 0, 0, 0),
('SH-C-02', 'C区二号书架-孤本特藏区', 2, 'RM-201', 36, 6, 6, 3, 0, 0);

INSERT INTO herb_knowledge_graph
(herb_id, herb_name, herb_cn_name, source_book, source_dynasty, usage_method, target_pests, efficacy, toxicity_level, compatibility) VALUES
('HRB-001', 'yun_cao', '芸草', '梦溪笔谈', '宋', '阴干后夹于书页间，每册3-5株', ['蠹鱼','衣鱼'], '香气驱虫，防蛀辟蠹，不伤纸墨', 'LOW', ['麝香','檀香']),
('HRB-002', 'huang_bo', '黄柏', '本草纲目', '明', '煎汁浸染纸张，晾干后装订', ['蠹鱼','甲虫','霉菌'], '苦味驱虫，性寒防霉，可千年不蛀', 'LOW', ['明矾','五倍子']),
('HRB-003', 'zhang_nao', '樟脑', '本草纲目', '明', '研末撒于书柜四角，或制香包悬挂', ['蠹虫','衣蛾','鼠妇'], '升华驱虫，挥发性强，速杀成虫', 'MEDIUM', ['薄荷','荆芥']),
('HRB-004', 'jiao_xiang', '椒香', '齐民要术', '北魏', '花椒研末，和泥糊书橱缝隙', ['白鱼','尘螨'], '麻味杀虫，性热辟湿', 'LOW', ['茱萸','干姜']),
('HRB-005', 'wu_bei_zi', '五倍子', '本草经疏', '明', '煎汁涂纸，或研末入香囊', ['霉菌','蠹鱼'], '固涩收敛，杀蛀防霉，兼固字迹', 'LOW', ['黄柏','明矾']),
('HRB-006', 'bai_fan', '明矾', '天工开物', '明', '水溶后浸纸，为防染纸基础', ['霉菌','酸化'], '固色防腐，抑酸护纸', 'LOW', ['五倍子','黄檗']),
('HRB-007', 'she_xiang', '麝香', '名医别录', '魏晋', '少量研末制香囊，置于书匣', ['百虫'], '开窍辟秽，芳香驱虫，药力强劲', 'HIGH', ['芸草','沉香']),
('HRB-008', 'ai_ye', '艾叶', '名医别录', '魏晋', '每年端午晒后夹书，或烟熏书库', ['蠹虫','霉菌','虫卵'], '温经辟秽，烟熏杀卵，取材便利', 'LOW', ['菖蒲','雄黄']);
