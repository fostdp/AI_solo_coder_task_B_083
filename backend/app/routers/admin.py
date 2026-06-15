from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any
from datetime import datetime
import uuid

from ..database import db_manager
from ..alerts import AlertManager, AlertThreshold
from ..config import settings

router = APIRouter(prefix="/api/admin", tags=["管理配置"])

alert_manager = AlertManager(
    dingtalk_webhook=settings.DINGTALK_WEBHOOK,
    smtp_config={
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "username": settings.SMTP_USER,
        "password": settings.SMTP_PASSWORD,
        "sender": settings.SMTP_SENDER,
        "use_tls": True
    },
    thresholds=AlertThreshold(
        yellow_ph=settings.ALERT_YELLOW_PH,
        orange_ph=settings.ALERT_ORANGE_PH,
        red_ph=settings.ALERT_RED_PH,
        yellow_mold=settings.ALERT_YELLOW_MOLD,
        orange_light=settings.ALERT_ORANGE_LIGHT
    )
)


@router.get("/config/thresholds")
async def get_thresholds():
    """获取告警阈值配置"""
    return {
        "ph": {
            "yellow": settings.ALERT_YELLOW_PH,
            "orange": settings.ALERT_ORANGE_PH,
            "red": settings.ALERT_RED_PH
        },
        "mold": {
            "yellow": settings.ALERT_YELLOW_MOLD
        },
        "light": {
            "orange": settings.ALERT_ORANGE_LIGHT
        }
    }


@router.post("/config/thresholds")
async def update_thresholds(config: Dict[str, Any] = Body(...)):
    """更新告警阈值（运行时）"""
    if "ph" in config:
        ph_cfg = config["ph"]
        if "yellow" in ph_cfg:
            alert_manager.thresholds.yellow_ph = ph_cfg["yellow"]
        if "orange" in ph_cfg:
            alert_manager.thresholds.orange_ph = ph_cfg["orange"]
        if "red" in ph_cfg:
            alert_manager.thresholds.red_ph = ph_cfg["red"]

    if "mold" in config:
        mold_cfg = config["mold"]
        if "yellow" in mold_cfg:
            alert_manager.thresholds.yellow_mold = mold_cfg["yellow"]

    if "light" in config:
        light_cfg = config["light"]
        if "orange" in light_cfg:
            alert_manager.thresholds.orange_light = light_cfg["orange"]

    return {"message": "阈值已更新", "thresholds": {
        "yellow_ph": alert_manager.thresholds.yellow_ph,
        "orange_ph": alert_manager.thresholds.orange_ph,
        "red_ph": alert_manager.thresholds.red_ph,
        "yellow_mold": alert_manager.thresholds.yellow_mold,
        "orange_light": alert_manager.thresholds.orange_light
    }}


@router.post("/alert/test")
async def test_alert(
    level: str = "yellow",
    shelf_id: str = "SHELF-01",
    slot_id: str = "SLOT-A1"
):
    """测试告警推送"""
    from ..alerts import Alert

    level_messages = {
        "red": ("这是一条测试红色告警，请检查系统配置。", 5.0, 5.5),
        "orange": ("这是一条测试橙色告警，请检查系统配置。", 5.8, 6.0),
        "yellow": ("这是一条测试黄色提醒，请检查系统配置。", 6.3, 6.5)
    }

    msg, val, threshold = level_messages.get(level, level_messages["yellow"])

    test_alert = Alert(
        alert_id=str(uuid.uuid4()),
        timestamp=datetime.now().isoformat(),
        shelf_id=shelf_id,
        slot_id=slot_id,
        alert_level=level,
        alert_type="test",
        alert_value=val,
        threshold=threshold,
        message=f"【测试】{msg}"
    )

    results = alert_manager.push_alert(test_alert, settings.ALERT_EMAILS)
    db_manager.insert_alert(test_alert.to_dict())

    return {
        "message": "测试告警已发送",
        "alert_id": test_alert.alert_id,
        "delivery_results": results
    }


@router.put("/alert/{alert_id}/handle")
async def handle_alert(alert_id: str):
    """标记告警为已处理"""
    try:
        query = """
            ALTER TABLE alerts
            UPDATE is_handled = 1, handle_time = now64()
            WHERE alert_id = %(alert_id)s
        """
        db_manager.client.execute(query, {"alert_id": alert_id})
        return {"message": "告警已标记为已处理", "alert_id": alert_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理告警失败: {str(e)}")


@router.get("/stats/database")
async def get_database_stats():
    """获取数据库统计信息"""
    try:
        env_count = db_manager.client.execute("SELECT count() FROM env_sensor_data")[0][0]
        ph_count = db_manager.client.execute("SELECT count() FROM ph_sensor_data")[0][0]
        alert_count = db_manager.client.execute("SELECT count() FROM alerts")[0][0]
        book_count = db_manager.client.execute("SELECT count() FROM books_info")[0][0]

        latest_env = db_manager.client.execute(
            "SELECT max(timestamp) FROM env_sensor_data"
        )[0][0]
        latest_ph = db_manager.client.execute(
            "SELECT max(timestamp) FROM ph_sensor_data"
        )[0][0]

        return {
            "env_sensor_records": env_count,
            "ph_sensor_records": ph_count,
            "alert_records": alert_count,
            "book_records": book_count,
            "latest_env_data": str(latest_env) if latest_env else None,
            "latest_ph_data": str(latest_ph) if latest_ph else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/stats/mqtt")
async def get_mqtt_stats():
    """获取MQTT连接状态"""
    from ..mqtt_subscriber import mqtt_subscriber

    return {
        "broker": settings.MQTT_BROKER,
        "port": settings.MQTT_PORT,
        "connected": mqtt_subscriber.connected,
        "env_topic": settings.MQTT_TOPIC_ENV,
        "ph_topic": settings.MQTT_TOPIC_PH
    }


@router.post("/data/ingest")
async def ingest_data(
    data_type: str,
    data: Dict[str, Any] = Body(...)
):
    """手动注入数据（测试用）"""
    try:
        if data_type == "env":
            db_manager.add_env_to_buffer(data)
            count = db_manager.flush_env_buffer()
        elif data_type == "ph":
            db_manager.add_ph_to_buffer(data)
            count = db_manager.flush_ph_buffer()
        else:
            raise HTTPException(status_code=400, detail=f"不支持的数据类型: {data_type}")

        return {"message": "数据已写入", "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据写入失败: {str(e)}")


@router.post("/data/simulate")
async def simulate_data(
    count: int = 100,
    days_back: int = 30
):
    """生成模拟历史数据"""
    import random
    from datetime import datetime, timedelta

    shelves = ["SHELF-01", "SHELF-02", "SHELF-03"]
    slots = ["SLOT-A1", "SLOT-A2", "SLOT-B1", "SLOT-B2"]

    env_data_list = []
    ph_data_list = []

    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_back)

    for i in range(count):
        timestamp = start_time + timedelta(
            seconds=random.randint(0, int((end_time - start_time).total_seconds()))
        )
        shelf = random.choice(shelves)
        slot = random.choice(slots)

        temp_base = 20 + random.gauss(0, 2)
        humid_base = 50 + random.gauss(0, 10)

        env_data = {
            "timestamp": timestamp,
            "sensor_id": f"ENV-{random.randint(1, 50):03d}",
            "shelf_id": shelf,
            "slot_id": slot,
            "temperature": round(temp_base, 2),
            "humidity": round(max(30, min(80, humid_base)), 2),
            "light": round(random.uniform(5, 80), 2),
            "voc": round(random.uniform(50, 500), 2),
            "mold_spore": round(random.uniform(10, 800), 1),
            "sensor_type": "environment"
        }
        env_data_list.append(env_data)

        if i % 5 == 0:
            ph_data = {
                "timestamp": timestamp,
                "sensor_id": f"PH-{random.randint(1, 20):03d}",
                "shelf_id": shelf,
                "slot_id": slot,
                "ph_value": round(random.uniform(5.5, 7.5), 2),
                "sensor_type": "ph"
            }
            ph_data_list.append(ph_data)

    db_manager.batch_insert_env_data(env_data_list)
    db_manager.batch_insert_ph_data(ph_data_list)

    return {
        "message": "模拟数据生成完成",
        "env_records": len(env_data_list),
        "ph_records": len(ph_data_list)
    }
