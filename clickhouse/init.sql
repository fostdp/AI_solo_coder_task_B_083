CREATE DATABASE IF NOT EXISTS ancient_medical_books
    COMMENT '古代医学文献馆藏微环境监测数据库';

USE ancient_medical_books;

CREATE TABLE IF NOT EXISTS env_sensor_data
(
    timestamp   DateTime64(3) DEFAULT now64(),
    sensor_id   String,
    shelf_id    String,
    slot_id     String,
    temperature Float64,
    humidity    Float64,
    light       Float64,
    voc         Float64,
    mold_spore  Float64,
    sensor_type String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (shelf_id, slot_id, sensor_id, timestamp)
TTL timestamp + INTERVAL 2 YEAR
COMMENT '环境传感器时序数据表';

CREATE TABLE IF NOT EXISTS ph_sensor_data
(
    timestamp   DateTime64(3) DEFAULT now64(),
    sensor_id   String,
    shelf_id    String,
    slot_id     String,
    ph_value    Float64,
    sensor_type String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (shelf_id, slot_id, sensor_id, timestamp)
TTL timestamp + INTERVAL 2 YEAR
COMMENT '纸张pH值检测时序数据表';

CREATE TABLE IF NOT EXISTS books_info
(
    book_id        String,
    shelf_id       String,
    slot_id        String,
    title          String,
    dynasty        String,
    author         String,
    category       String,
    material       String,
    publication_year Int32,
    condition      String,
    create_time    DateTime DEFAULT now(),
    update_time    DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (shelf_id, slot_id, book_id)
COMMENT '古籍基本信息表';

CREATE TABLE IF NOT EXISTS alerts
(
    alert_id    String,
    timestamp   DateTime64(3) DEFAULT now64(),
    shelf_id    String,
    slot_id     String,
    alert_level String,
    alert_type  String,
    alert_value Float64,
    threshold   Float64,
    message     String,
    is_handled  UInt8 DEFAULT 0,
    handle_time DateTime64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (alert_level, timestamp)
TTL timestamp + INTERVAL 1 YEAR
COMMENT '告警记录表';

CREATE TABLE IF NOT EXISTS aging_prediction
(
    prediction_date Date,
    shelf_id        String,
    slot_id         String,
    ph_30d          Float64,
    ph_90d          Float64,
    ph_180d         Float64,
    aging_rate      Float64,
    mold_risk       Float64,
    model_version   String DEFAULT 'v1.0'
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(prediction_date)
ORDER BY (prediction_date, shelf_id, slot_id)
TTL prediction_date + INTERVAL 6 MONTH
COMMENT '纸张老化预测表';

CREATE MATERIALIZED VIEW IF NOT EXISTS env_hourly_mv
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour_start)
ORDER BY (shelf_id, slot_id, hour_start)
AS
SELECT
    toStartOfHour(timestamp) AS hour_start,
    shelf_id,
    slot_id,
    avg(temperature)    AS avg_temperature,
    max(temperature)    AS max_temperature,
    min(temperature)    AS min_temperature,
    avg(humidity)       AS avg_humidity,
    max(humidity)       AS max_humidity,
    min(humidity)       AS min_humidity,
    avg(light)          AS avg_light,
    avg(voc)            AS avg_voc,
    avg(mold_spore)     AS avg_mold_spore,
    count()             AS sample_count
FROM env_sensor_data
GROUP BY hour_start, shelf_id, slot_id;

CREATE MATERIALIZED VIEW IF NOT EXISTS ph_daily_mv
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day_start)
ORDER BY (shelf_id, slot_id, day_start)
AS
SELECT
    toStartOfDay(timestamp) AS day_start,
    shelf_id,
    slot_id,
    avg(ph_value)       AS avg_ph,
    max(ph_value)       AS max_ph,
    min(ph_value)       AS min_ph,
    count()             AS sample_count
FROM ph_sensor_data
GROUP BY day_start, shelf_id, slot_id;

CREATE TABLE IF NOT EXISTS disease_knowledge_graph
(
    disease_type    String,
    disease_name    String,
    description     String,
    herbs           Array(String),
    prescriptions   Array(String),
    references      Array(String),
    create_time     DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY disease_type
COMMENT '古籍病害与药方知识图谱';

INSERT INTO disease_knowledge_graph (disease_type, disease_name, description, herbs, prescriptions, references) VALUES
('acidification', '纸张酸化', '纸张因环境因素导致pH值下降，引起纸张脆化变黄', ['黄柏', '石灰', '碳酸钙'], ['黄柏染纸法', '石灰水脱酸法'], ['《天工开物》', '《纸墨笺》']),
('mold', '霉变', '霉菌在纸张表面生长，导致纸张污损、强度下降', ['芸草', '樟脑', '苍术', '艾叶'], ['芸香避蠹法', '苍术熏库法'], ['《梦溪笔谈》', '《本草纲目》']),
('insect', '虫蛀', '蛀虫啃食纸张，造成孔洞和缺损', ['芸草', '雄黄', '雌黄', '苦楝'], ['芸草藏书法', '雄黄熏书法', '苦楝纸法'], ['《齐民要术》', '《本草纲目》', '《藏书纪要》']),
('light_damage', '光照老化', '光照导致纸张纤维素降解、褪色', ['槐花', '五倍子', '皂角'], ['槐花染纸防光法', '五倍子固色法'], ['《天工开物》', '《装潢志》']),
('humidity_damage', '潮湿损伤', '高湿导致纸张变形、粘连、滋生霉菌', ['石灰', '木炭', '皂角'], ['石灰除湿法', '木炭吸潮法'], ['《便民图纂》', '《多能鄙事》']);

INSERT INTO books_info (book_id, shelf_id, slot_id, title, dynasty, author, category, material, publication_year, condition) VALUES
('BK001', 'SHELF-01', 'SLOT-A1', '本草纲目（明万历刻本）', '明', '李时珍', '本草', '竹纸', 1596, '良好'),
('BK002', 'SHELF-01', 'SLOT-A2', '黄帝内经素问（明嘉靖版）', '明', '佚名', '医经', '棉纸', 1547, '轻微酸化'),
('BK003', 'SHELF-01', 'SLOT-B1', '伤寒论（清康熙刻本）', '清', '张仲景', '伤寒', '竹纸', 1683, '良好'),
('BK004', 'SHELF-01', 'SLOT-B2', '金匮要略（清乾隆版）', '清', '张仲景', '伤寒', '棉纸', 1742, '良好'),
('BK005', 'SHELF-02', 'SLOT-A1', '千金要方（明万历刻本）', '明', '孙思邈', '方书', '竹纸', 1605, '轻微虫蛀'),
('BK006', 'SHELF-02', 'SLOT-A2', '外台秘要（明崇祯版）', '明', '王焘', '方书', '棉纸', 1640, '良好'),
('BK007', 'SHELF-02', 'SLOT-B1', '证类本草（明成化刻本）', '明', '唐慎微', '本草', '竹纸', 1485, '严重酸化'),
('BK008', 'SHELF-02', 'SLOT-B2', '本草经疏（明天启版）', '明', '缪希雍', '本草', '棉纸', 1625, '良好'),
('BK009', 'SHELF-03', 'SLOT-A1', '脉经（明万历刻本）', '明', '王叔和', '诊断', '竹纸', 1587, '轻微霉变'),
('BK010', 'SHELF-03', 'SLOT-A2', '针灸甲乙经（清康熙版）', '清', '皇甫谧', '针灸', '棉纸', 1699, '良好'),
('BK011', 'SHELF-03', 'SLOT-B1', '景岳全书（清乾隆刻本）', '清', '张介宾', '综合', '竹纸', 1750, '良好'),
('BK012', 'SHELF-03', 'SLOT-B2', '医宗金鉴（清乾隆武英殿版）', '清', '吴谦', '综合', '开化纸', 1742, '良好');
