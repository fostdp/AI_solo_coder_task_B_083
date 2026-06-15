from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timedelta

from ..algorithms import ArrheniusAgingModel, MoldGrowthModel, calculate_combined_risk
from ..knowledge import KnowledgeGraphService
from ..database import db_manager

router = APIRouter(prefix="/api/analysis", tags=["分析预测"])
kg_service = KnowledgeGraphService()


@router.post("/predict/aging")
async def predict_aging(
    initial_ph: float,
    temperature: float,
    humidity: float,
    paper_type: str = "bamboo",
    days: int = Query(90, ge=1, le=3650)
):
    """预测纸张老化情况"""
    model = ArrheniusAgingModel(paper_type=paper_type)

    ph_prediction = model.predict_ph_multiple(initial_ph, temperature, humidity, [30, 90, 180, 365, days])

    aging_info = model.aging_index(temperature, humidity, initial_ph)

    history = model.daily_ph_history(
        initial_ph,
        datetime.now().strftime("%Y-%m-%d"),
        temperature,
        humidity,
        days
    )

    return {
        "initial_ph": initial_ph,
        "temperature": temperature,
        "humidity": humidity,
        "paper_type": paper_type,
        "prediction_days": days,
        "ph_predictions": ph_prediction,
        "aging_index": aging_info,
        "daily_history": history
    }


@router.post("/predict/mold")
async def predict_mold(
    temperature: float,
    humidity: float,
    initial_spores: float = 10.0,
    mold_type: str = "mixed",
    days: int = Query(30, ge=1, le=365)
):
    """预测霉菌生长情况"""
    model = MoldGrowthModel(mold_type=mold_type)

    risk = model.mold_risk_index(temperature, humidity, initial_spores)
    is_active = model.is_active_mold(temperature, humidity, initial_spores)
    optimal = model.optimal_conditions()

    daily_simulation = model.daily_growth_simulation(temperature, humidity, initial_spores, days)

    return {
        "temperature": temperature,
        "humidity": humidity,
        "initial_spores": initial_spores,
        "mold_type": mold_type,
        "risk_assessment": risk,
        "is_active_mold": is_active,
        "optimal_conditions": optimal,
        "daily_simulation": daily_simulation
    }


@router.post("/risk/comprehensive")
async def comprehensive_risk(
    temperature: float,
    humidity: float,
    ph_value: float,
    mold_spores: Optional[float] = None,
    light: Optional[float] = None
):
    """综合风险评估"""
    risk = calculate_combined_risk(temperature, humidity, ph_value, mold_spores)

    knowledge = kg_service.get_comprehensive_recommendation(risk)

    return {
        "risk_assessment": risk,
        "knowledge_recommendation": knowledge
    }


@router.get("/knowledge/diseases")
async def get_disease_types():
    """获取所有病害类型"""
    diseases = kg_service.get_all_disease_types()
    return {"diseases": diseases}


@router.get("/knowledge/disease/{disease_type}")
async def get_disease_knowledge(disease_type: str):
    """获取指定病害的详细知识和防治方案"""
    info = kg_service.get_recommendations_by_disease(disease_type)
    if "error" in info:
        raise HTTPException(status_code=404, detail=info["error"])
    return info


@router.get("/knowledge/herb/{herb_name}")
async def get_herb_info(herb_name: str):
    """获取药材详情"""
    herb = kg_service.search_herb(herb_name)
    if not herb:
        raise HTTPException(status_code=404, detail=f"未找到药材: {herb_name}")
    return herb


@router.get("/heatmap")
async def get_heatmap_data(type: str = "ph"):
    """获取热力图数据"""
    shelves = db_manager.get_all_shelves_status()

    heatmap_data = []
    for shelf in shelves:
        value = 0
        level = "normal"

        if type == "ph":
            value = shelf.get("ph_value", 7.0)
            if value < 5.5:
                level = "danger"
            elif value < 6.5:
                level = "warning"
            else:
                level = "normal"
        elif type == "mold":
            value = shelf.get("mold_spore", 0)
            if value > 5000:
                level = "danger"
            elif value > 500:
                level = "warning"
            else:
                level = "normal"
        elif type == "acidification":
            ph = shelf.get("ph_value", 7.0)
            value = max(0, (6.5 - ph) / 2.0 * 100) if ph < 6.5 else 0
            if value > 75:
                level = "danger"
            elif value > 30:
                level = "warning"
            else:
                level = "normal"
        elif type == "insect":
            value = shelf.get("mold_spore", 0) * 0.1
            if value > 500:
                level = "danger"
            elif value > 100:
                level = "warning"
            else:
                level = "normal"

        heatmap_data.append({
            "shelf_id": shelf["shelf_id"],
            "slot_id": shelf["slot_id"],
            "value": value,
            "level": level,
            "book_title": shelf.get("book_title", "")
        })

    return {"type": type, "data": heatmap_data}


@router.post("/batch/predict")
async def batch_predict(shelf_ids: List[str] = None):
    """批量预测所有书架的老化和病害风险"""
    shelves = db_manager.get_all_shelves_status()

    if shelf_ids:
        shelves = [s for s in shelves if s["shelf_id"] in shelf_ids]

    results = []
    aging_model = ArrheniusAgingModel()
    mold_model = MoldGrowthModel()

    for shelf in shelves:
        temp = shelf.get("temperature", 20)
        humid = shelf.get("humidity", 50)
        ph = shelf.get("ph_value", 7.0)
        mold = shelf.get("mold_spore", 50)

        aging_info = aging_model.aging_index(temp, humid, ph)
        ph_pred_90 = aging_model.predict_ph(ph, temp, humid, 90)
        mold_risk = mold_model.mold_risk_index(temp, humid, mold)
        combined = calculate_combined_risk(temp, humid, ph, mold)

        results.append({
            "shelf_id": shelf["shelf_id"],
            "slot_id": shelf["slot_id"],
            "book_title": shelf.get("book_title", ""),
            "current_ph": ph,
            "predicted_ph_90d": ph_pred_90,
            "aging_severity": aging_info["aging_severity"],
            "mold_risk_level": mold_risk["risk_level"],
            "overall_risk": combined["overall_risk_level"],
            "risk_score": combined["overall_risk_score"],
            "primary_risks": combined["primary_risks"]
        })

    results.sort(key=lambda x: x["risk_score"], reverse=True)

    return {
        "total": len(results),
        "predictions": results
    }
