"""
消息协议定义
模块间通信的统一消息格式
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
import json


@dataclass
class Message:
    """基础消息类"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    message_type: str = "data"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class SensorData(Message):
    """传感器数据消息"""
    sensor_id: str = ""
    shelf_id: str = ""
    slot_id: str = ""
    sensor_type: str = ""  # "environment" or "ph"
    data: Dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.message_type = "sensor_data"


@dataclass
class EnvSensorData(SensorData):
    """环境传感器数据"""
    temperature: float = 0.0
    humidity: float = 0.0
    light: float = 0.0
    voc: float = 0.0
    mold_spore: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        self.sensor_type = "environment"


@dataclass
class PhSensorData(SensorData):
    """pH传感器数据"""
    ph_value: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        self.sensor_type = "ph"


@dataclass
class AgingPredictionRequest(Message):
    """老化预测请求"""
    shelf_id: str = ""
    slot_id: str = ""
    paper_type: str = "bamboo"
    current_ph: float = 7.0
    temperature: float = 20.0
    humidity: float = 50.0
    ph_history: List[Dict[str, Any]] = field(default_factory=list)
    prediction_days: List[int] = field(default_factory=lambda: [30, 90, 180])

    def __post_init__(self):
        self.message_type = "aging_prediction_request"


@dataclass
class AgingPredictionResult(Message):
    """老化预测结果"""
    shelf_id: str = ""
    slot_id: str = ""
    paper_type: str = "bamboo"
    ph_decay_rate: float = 0.0
    predicted_lifetime_years: float = 0.0
    ph_predictions: Dict[int, float] = field(default_factory=dict)
    severity: str = "normal"
    daily_history: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self.message_type = "aging_prediction_result"


@dataclass
class MoldPredictionRequest(Message):
    """霉菌预测请求"""
    shelf_id: str = ""
    slot_id: str = ""
    temperature: float = 20.0
    humidity: float = 50.0
    current_spores: float = 0.0
    mold_type: str = "mixed"

    def __post_init__(self):
        self.message_type = "mold_prediction_request"


@dataclass
class MoldPredictionResult(Message):
    """霉菌预测结果"""
    shelf_id: str = ""
    slot_id: str = ""
    risk_score: float = 0.0
    risk_level: str = "negligible"
    growth_rate: float = 0.0
    predicted_spores_7d: float = 0.0
    predicted_spores_30d: float = 0.0
    is_active_mold: bool = False

    def __post_init__(self):
        self.message_type = "mold_prediction_result"


@dataclass
class AlertMessage(Message):
    """告警消息"""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    shelf_id: str = ""
    slot_id: str = ""
    alert_level: str = "yellow"  # "yellow", "orange", "red"
    alert_type: str = ""  # "ph_low", "mold_spore_high", "light_high", "active_mold"
    alert_value: float = 0.0
    threshold: float = 0.0
    message: str = ""
    is_handled: bool = False

    def __post_init__(self):
        self.message_type = "alert"


@dataclass
class ClickHouseRecord(Message):
    """ClickHouse写入记录"""
    table_name: str = ""
    record: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.message_type = "clickhouse_record"


@dataclass
class ControlMessage(Message):
    """控制消息"""
    action: str = ""  # "start", "stop", "flush", "status"
    params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.message_type = "control"


@dataclass
class BookMetaExtractRequest(Message):
    """医籍元数据提取请求"""
    book_id: str = ""
    shelf_id: str = ""
    slot_id: str = ""
    image_path: str = ""

    def __post_init__(self):
        self.message_type = "book_meta_extract_request"


@dataclass
class BookMetaExtractResult(Message):
    """医籍元数据提取结果"""
    book_id: str = ""
    shelf_id: str = ""
    slot_id: str = ""
    paper_type: str = ""
    binding_type: str = ""
    repair_records: List[str] = field(default_factory=list)
    fiber_density: float = 0.0
    ink_type: str = ""
    ocr_confidence: float = 0.0
    text_features: List[float] = field(default_factory=list)
    ocr_text: str = ""

    def __post_init__(self):
        self.message_type = "book_meta_extract_result"


@dataclass
class EfficacyEvaluationRequest(Message):
    """药方有效性评估请求"""
    prescription: str = ""
    shelf_id: str = ""
    slot_id: str = ""
    treatment_group: str = ""
    duration_days: int = 30

    def __post_init__(self):
        self.message_type = "efficacy_evaluation_request"


@dataclass
class EfficacyEvaluationResult(Message):
    """药方有效性评估结果"""
    prescription: str = ""
    shelf_id: str = ""
    slot_id: str = ""
    treatment_group: str = ""
    reduction_rate: float = 0.0
    efficacy_mean: float = 0.0
    efficacy_ci_low: float = 0.0
    efficacy_ci_high: float = 0.0
    posterior_mean: float = 0.0
    posterior_var: float = 0.0
    sample_size: int = 0
    spores_before: float = 0.0
    spores_after: float = 0.0

    def __post_init__(self):
        self.message_type = "efficacy_evaluation_result"


@dataclass
class CrossLibraryComparisonResult(Message):
    """跨馆藏比对结果"""
    record_date: str = ""
    library_name: str = ""
    metric: str = ""
    value: float = 0.0
    percentile: float = 0.0
    percentile_rank: int = 0
    total_libraries: int = 0
    is_anomaly: bool = False
    data_source: str = ""

    def __post_init__(self):
        self.message_type = "cross_library_comparison_result"


@dataclass
class SpreadPredictionRequest(Message):
    """传播预测请求"""
    prediction_date: str = ""
    model_type: str = "SEIR"
    start_shelf_id: str = ""
    days: int = 30
    initial_infected: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.message_type = "spread_prediction_request"


@dataclass
class SpreadPredictionResult(Message):
    """传播预测结果"""
    prediction_date: str = ""
    model_type: str = "SEIR"
    day: int = 0
    shelf_id: str = ""
    slot_id: str = ""
    S: float = 0.0
    E: float = 0.0
    I: float = 0.0
    R: float = 0.0
    infection_prob: float = 0.0
    is_hotspot: bool = False
    spread_from: str = ""
    edge_weight: float = 0.0

    def __post_init__(self):
        self.message_type = "spread_prediction_result"


MESSAGE_CLASSES = {
    "sensor_data": SensorData,
    "aging_prediction_request": AgingPredictionRequest,
    "aging_prediction_result": AgingPredictionResult,
    "mold_prediction_request": MoldPredictionRequest,
    "mold_prediction_result": MoldPredictionResult,
    "alert": AlertMessage,
    "clickhouse_record": ClickHouseRecord,
    "control": ControlMessage,
    "book_meta_extract_request": BookMetaExtractRequest,
    "book_meta_extract_result": BookMetaExtractResult,
    "efficacy_evaluation_request": EfficacyEvaluationRequest,
    "efficacy_evaluation_result": EfficacyEvaluationResult,
    "cross_library_comparison": CrossLibraryComparisonResult,
    "spread_prediction_request": SpreadPredictionRequest,
    "spread_prediction_result": SpreadPredictionResult,
}


def deserialize_message(data: Dict[str, Any]) -> Message:
    """从字典反序列化消息"""
    msg_type = data.get("message_type", "data")
    msg_class = MESSAGE_CLASSES.get(msg_type, Message)
    try:
        filtered_data = {k: v for k, v in data.items() if k in msg_class.__dataclass_fields__}
        return msg_class(**filtered_data)
    except Exception:
        return Message(**{k: v for k, v in data.items() if k in Message.__dataclass_fields__})


def serialize_message(msg: Message) -> Dict[str, Any]:
    """序列化消息为字典"""
    return msg.to_dict()
