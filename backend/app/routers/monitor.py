from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta

from ..database import db_manager
from ..algorithms import ArrheniusAgingModel, MoldGrowthModel, calculate_combined_risk
from ..knowledge import KnowledgeGraphService

router = APIRouter(prefix="/api", tags=["监测数据"])
kg_service = KnowledgeGraphService()


@router.get("/overview")
async def get_overview():
    """获取系统概览数据"""
    shelves = db_manager.get_all_shelves_status()
    recent_alerts = db_manager.get_recent_alerts(limit=10)
    books = db_manager.get_books_info()

    total_shelves = len(set(s["shelf_id"] for s in shelves))
    total_books = len(books)

    normal_count = 0
    warning_count = 0
    danger_count = 0

    for shelf in shelves:
        ph = shelf.get("ph_value", 7.0)
        mold = shelf.get("mold_spore", 0)
        if ph < 5.5 or mold > 5000:
            danger_count += 1
        elif ph < 6.5 or mold > 500:
            warning_count += 1
        else:
            normal_count += 1

    return {
        "total_shelves": total_shelves,
        "total_books": total_books,
        "total_slots": len(shelves),
        "env_sensor_count": 50,
        "ph_sensor_count": 20,
        "status_summary": {
            "normal": normal_count,
            "warning": warning_count,
            "danger": danger_count
        },
        "recent_alerts": recent_alerts[:5],
        "last_update": datetime.now().isoformat()
    }


@router.get("/shelves")
async def get_all_shelves():
    """获取所有书架状态"""
    shelves = db_manager.get_all_shelves_status()

    result = {}
    for shelf in shelves:
        shelf_id = shelf["shelf_id"]
        if shelf_id not in result:
            result[shelf_id] = []
        result[shelf_id].append(shelf)

    return {"shelves": result}


@router.get("/shelf/{shelf_id}")
async def get_shelf_detail(shelf_id: str):
    """获取指定书架的详细信息"""
    shelves = db_manager.get_all_shelves_status()
    shelf_slots = [s for s in shelves if s["shelf_id"] == shelf_id]

    if not shelf_slots:
        raise HTTPException(status_code=404, detail=f"书架 {shelf_id} 不存在")

    books = db_manager.get_books_info(shelf_id=shelf_id)

    avg_temp = sum(s["temperature"] for s in shelf_slots) / len(shelf_slots) if shelf_slots else 0
    avg_humid = sum(s["humidity"] for s in shelf_slots) / len(shelf_slots) if shelf_slots else 0
    avg_ph = sum(s["ph_value"] for s in shelf_slots) / len(shelf_slots) if shelf_slots else 0

    return {
        "shelf_id": shelf_id,
        "total_slots": len(shelf_slots),
        "slots": shelf_slots,
        "books": books,
        "average": {
            "temperature": round(avg_temp, 2),
            "humidity": round(avg_humid, 2),
            "ph": round(avg_ph, 2)
        }
    }


@router.get("/slot/{shelf_id}/{slot_id}")
async def get_slot_detail(shelf_id: str, slot_id: str, days: int = Query(90, ge=1, le=365)):
    """获取指定格口的详细数据和趋势"""
    env_trend = db_manager.get_env_trend(shelf_id, slot_id, days=days)
    ph_trend = db_manager.get_ph_trend(shelf_id, slot_id, days=days)
    books = db_manager.get_books_info(shelf_id=shelf_id, slot_id=slot_id)

    current_temp = env_trend[-1]["avg_temperature"] if env_trend else 20
    current_humid = env_trend[-1]["avg_humidity"] if env_trend else 50
    current_ph = ph_trend[-1]["avg_ph"] if ph_trend else 7.0
    current_mold = env_trend[-1]["avg_mold_spore"] if env_trend else 50

    aging_model = ArrheniusAgingModel()
    aging_info = aging_model.aging_index(current_temp, current_humid, current_ph)
    ph_prediction = aging_model.predict_ph_multiple(current_ph, current_temp, current_humid, [30, 90, 180])

    mold_model = MoldGrowthModel()
    mold_risk = mold_model.mold_risk_index(current_temp, current_humid, current_mold)

    combined_risk = calculate_combined_risk(current_temp, current_humid, current_ph, current_mold)

    knowledge_rec = kg_service.get_comprehensive_recommendation(combined_risk)

    return {
        "shelf_id": shelf_id,
        "slot_id": slot_id,
        "current": {
            "temperature": current_temp,
            "humidity": current_humid,
            "ph": current_ph,
            "mold_spore": current_mold,
            "voc": env_trend[-1]["avg_voc"] if env_trend else 0,
            "light": env_trend[-1]["avg_light"] if env_trend else 0
        },
        "env_trend": env_trend,
        "ph_trend": ph_trend,
        "books": books,
        "prediction": {
            "ph": {
                "30d": ph_prediction.get(30, 0),
                "90d": ph_prediction.get(90, 0),
                "180d": ph_prediction.get(180, 0)
            },
            "aging_info": aging_info,
            "mold_risk": mold_risk
        },
        "risk_assessment": combined_risk,
        "knowledge_recommendation": knowledge_rec
    }


@router.get("/books")
async def get_books(shelf_id: Optional[str] = None, category: Optional[str] = None):
    """获取古籍列表"""
    books = db_manager.get_books_info(shelf_id=shelf_id)

    if category:
        books = [b for b in books if b.get("category") == category]

    return {"total": len(books), "books": books}


@router.get("/books/{book_id}")
async def get_book_detail(book_id: str):
    """获取单本古籍详情"""
    books = db_manager.get_books_info()
    book = next((b for b in books if b["book_id"] == book_id), None)

    if not book:
        raise HTTPException(status_code=404, detail=f"古籍 {book_id} 不存在")

    env_trend = db_manager.get_env_trend(book["shelf_id"], book["slot_id"], days=90)
    ph_trend = db_manager.get_ph_trend(book["shelf_id"], book["slot_id"], days=90)

    return {
        "book": book,
        "env_trend": env_trend,
        "ph_trend": ph_trend
    }


@router.get("/alerts")
async def get_alerts(level: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    """获取告警列表"""
    alerts = db_manager.get_recent_alerts(level=level, limit=limit)
    return {"total": len(alerts), "alerts": alerts}


@router.get("/alerts/summary")
async def get_alert_summary():
    """获取告警统计摘要"""
    alerts = db_manager.get_recent_alerts(limit=500)

    today = datetime.now().date()
    today_alerts = [a for a in alerts if a.get("timestamp") and
                    datetime.fromisoformat(str(a["timestamp"])).date() == today]

    by_level = {}
    by_type = {}

    for alert in alerts:
        level = alert.get("alert_level", "unknown")
        alert_type = alert.get("alert_type", "unknown")
        by_level[level] = by_level.get(level, 0) + 1
        by_type[alert_type] = by_type.get(alert_type, 0) + 1

    return {
        "total": len(alerts),
        "today": len(today_alerts),
        "by_level": by_level,
        "by_type": by_type,
        "unhandled": sum(1 for a in alerts if not a.get("is_handled"))
    }
