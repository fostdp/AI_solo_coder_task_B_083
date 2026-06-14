"""
FastAPI REST API 路由定义
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..database import get_ch
from ..algorithms.paper_aging import paper_aging_model
from ..algorithms.mold_growth import mold_growth_model
from ..services.knowledge_graph import knowledge_graph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


# ---------- Pydantic Schemas ----------

class PredictionRequest(BaseModel):
    slot_id: str
    initial_ph: float = Field(6.5, ge=3.0, le=9.0)
    avg_temp_c: float = Field(22.0, ge=-10, le=60)
    avg_rh: float = Field(50.0, ge=0, le=100)
    avg_voc_ppm: float = Field(0.5, ge=0, le=50)
    book_age_years: float = Field(150.0, ge=0, le=2000)
    paper_type: str = Field("default", description="纸张原料类型：bamboo/bark/xuan/hemp/default")


class HerbRecommendRequest(BaseModel):
    disease_types: List[str] = []
    mold_risk: float = 0.0
    insect_risk: float = 0.0
    ph_value: Optional[float] = None
    top_k: int = 4
    book_dynasty: str = ""


class AlertAckRequest(BaseModel):
    event_id: str
    ack_user: str = "admin"


# ---------- Utility ----------

def _ts_ms_to_str(ts_ms) -> str:
    if isinstance(ts_ms, (int, float)):
        if ts_ms > 1e12:
            ts_ms = ts_ms / 1000.0
        return datetime.fromtimestamp(ts_ms, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return str(ts_ms)


# ---------- 健康检查 ----------

@router.get("/health", tags=["System"])
async def health_check():
    ch_ok = True
    ch_msg = "ok"
    try:
        get_ch().query("SELECT 1")
    except Exception as e:
        ch_ok = False
        ch_msg = str(e)
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clickhouse": {"ok": ch_ok, "msg": ch_msg},
    }


# ---------- 书架元数据 ----------

@router.get("/shelves", tags=["Metadata"])
async def list_shelves():
    sql = "SELECT * FROM bookshelf_metadata ORDER BY shelf_id"
    return {"data": get_ch().query(sql)}


@router.get("/shelves/{shelf_id}/slots", tags=["Metadata"])
async def list_slots(shelf_id: str):
    sql = "SELECT * FROM book_slot_metadata WHERE shelf_id = {sid:String} ORDER BY row_num, col_num"
    rows = get_ch().query(sql, {"sid": shelf_id})
    if not rows:
        return {
            "data": _generate_dummy_slots(shelf_id),
            "note": "dummy data generated"
        }
    return {"data": rows}


def _estimate_book_age(dynasty: Optional[str], slot_id: Optional[str] = None) -> float:
    now_year = datetime.now().year
    dy = str(dynasty or "").strip()
    if "宋" in dy or dy in ("Song", "song"):
        return float(now_year - 1200)
    if "元" in dy or dy in ("Yuan", "yuan"):
        return float(now_year - 1360)
    if "明" in dy or dy in ("Ming", "ming"):
        return float(now_year - 1600)
    if "清" in dy or dy in ("Qing", "qing"):
        return float(now_year - 1820)
    if "民国" in dy or dy in ("Minguo", "Republic", "ROC"):
        return float(now_year - 1930)
    if "唐" in dy or dy in ("Tang", "tang"):
        return float(now_year - 1200)
    if slot_id:
        seed = abs(hash(slot_id)) % 10
        if seed < 4:
            return float(now_year - 1780)
        if seed < 8:
            return float(now_year - 1600)
        return float(now_year - 1880)
    return 180.0


def _generate_dummy_slots(shelf_id: str) -> List[Dict]:
    shelf_sql = "SELECT * FROM bookshelf_metadata WHERE shelf_id = {sid:String}"
    shelf = get_ch().query_one(shelf_sql, {"sid": shelf_id})
    if not shelf:
        rows_c, cols_c = 6, 8
    else:
        rows_c = int(shelf.get("rows_count", 6))
        cols_c = int(shelf.get("cols_count", 8))
    titles = [
        "本草纲目", "伤寒论", "金匮要略", "黄帝内经", "千金要方",
        "本草经疏", "景岳全书", "医宗金鉴", "外科正宗", "针灸甲乙经",
        "脉经", "诸病源候论", "温病条辨", "温热经纬", "脾胃论",
        "兰室秘藏", "格致余论", "儒门事亲", "河间六书", "东垣试效方",
    ]
    dynasties = ["明", "清"]
    types = ["刻本", "医案", "手稿"]
    paper_types = ["bamboo", "bark", "xuan", "hemp", "default"]
    data = []
    idx = 0
    for r in range(1, rows_c + 1):
        for c in range(1, cols_c + 1):
            env_no = (idx % 50) + 1
            ph_no = (idx % 20) + 1
            pt = paper_types[idx % len(paper_types)]
            if dynasties[idx % 2] == "明":
                pt = "bamboo" if idx % 3 != 0 else "xuan"
            else:
                pt = "bark" if idx % 3 != 0 else "hemp"
            data.append({
                "slot_id": f"{shelf_id}-R{r:02d}-C{c:02d}",
                "shelf_id": shelf_id,
                "row_num": r,
                "col_num": c,
                "book_title": titles[idx % len(titles)],
                "book_dynasty": dynasties[idx % 2],
                "book_type": types[idx % 3],
                "book_count": 3 + (idx % 15),
                "paper_type": pt,
                "sensor_env_id": f"ENV-{env_no:03d}",
                "sensor_ph_id": f"PH-{ph_no:03d}",
            })
            idx += 1
    return data


# ---------- 微环境监测 ----------

@router.get("/env/latest", tags=["Monitoring"])
async def get_latest_env(shelf_id: Optional[str] = None):
    sql = """
        SELECT *
        FROM env_sensor_data
        WHERE timestamp = (SELECT max(timestamp) FROM env_sensor_data)
    """
    if shelf_id:
        sql += " AND shelf_id = {sid:String}"
        params = {"sid": shelf_id}
    else:
        params = {}
    sql += " ORDER BY shelf_id, sensor_id"
    rows = get_ch().query(sql, params)
    if not rows:
        return {"data": _generate_dummy_env(shelf_id), "note": "dummy latest env data"}
    return {"data": rows}


@router.get("/env/trend", tags=["Monitoring"])
async def get_env_trend(
    shelf_id: Optional[str] = None,
    slot_id: Optional[str] = None,
    sensor_id: Optional[str] = None,
    hours: int = Query(24 * 90, ge=1, le=24 * 365),
):
    start_ts = datetime.now(timezone.utc) - timedelta(hours=hours)
    where_parts = ["timestamp >= {start:DateTime64(3)}"]
    params = {"start": int(start_ts.timestamp() * 1000)}
    if shelf_id:
        where_parts.append("shelf_id = {sid:String}")
        params["sid"] = shelf_id
    if slot_id:
        where_parts.append("slot_id = {slid:String}")
        params["slid"] = slot_id
    if sensor_id:
        where_parts.append("sensor_id = {senid:String}")
        params["senid"] = sensor_id

    granularity = "5 minute"
    if hours > 24 * 30:
        granularity = "1 hour"
    if hours > 24 * 120:
        granularity = "1 day"

    sql = f"""
        SELECT
            toStartOfInterval(timestamp, INTERVAL {granularity}) AS ts_bucket,
            avg(temperature)   AS temp_avg,
            max(temperature)   AS temp_max,
            min(temperature)   AS temp_min,
            avg(humidity)      AS humi_avg,
            max(humidity)      AS humi_max,
            min(humidity)      AS humi_min,
            avg(light_lux)     AS light_avg,
            max(light_lux)     AS light_max,
            avg(voc_ppm)       AS voc_avg,
            avg(mold_spores)   AS mold_avg,
            sum(active_mold)   AS active_mold_cnt
        FROM env_sensor_data
        WHERE {' AND '.join(where_parts)}
        GROUP BY ts_bucket
        ORDER BY ts_bucket ASC
    """
    rows = get_ch().query(sql, params)
    if not rows:
        return {"data": _generate_dummy_trend(hours, granularity), "note": "dummy trend data"}
    return {"data": rows}


# ---------- pH 监测 ----------

@router.get("/ph/latest", tags=["Monitoring"])
async def get_latest_ph(shelf_id: Optional[str] = None, slot_id: Optional[str] = None):
    sql = """
        SELECT *
        FROM ph_sensor_data
        WHERE timestamp = (SELECT max(timestamp) FROM ph_sensor_data)
    """
    params = {}
    if shelf_id:
        sql += " AND shelf_id = {sid:String}"
        params["sid"] = shelf_id
    if slot_id:
        sql += " AND slot_id = {slid:String}"
        params["slid"] = slot_id
    sql += " ORDER BY slot_id"
    rows = get_ch().query(sql, params)
    if not rows:
        return {"data": _generate_dummy_ph(shelf_id, slot_id), "note": "dummy ph data"}
    return {"data": rows}


@router.get("/ph/trend", tags=["Monitoring"])
async def get_ph_trend(
    shelf_id: Optional[str] = None,
    slot_id: Optional[str] = None,
    sensor_id: Optional[str] = None,
    days: int = Query(90, ge=1, le=730),
):
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    where_parts = ["timestamp >= {start:DateTime64(3)}"]
    params = {"start": int(start_date.timestamp() * 1000)}
    if shelf_id:
        where_parts.append("shelf_id = {sid:String}")
        params["sid"] = shelf_id
    if slot_id:
        where_parts.append("slot_id = {slid:String}")
        params["slid"] = slot_id
    if sensor_id:
        where_parts.append("sensor_id = {senid:String}")
        params["senid"] = sensor_id

    sql = f"""
        SELECT
            toDate(timestamp) AS day,
            avg(ph_value) AS ph_avg,
            min(ph_value) AS ph_min,
            max(ph_value) AS ph_max,
            count()       AS samples
        FROM ph_sensor_data
        WHERE {' AND '.join(where_parts)}
        GROUP BY day
        ORDER BY day ASC
    """
    rows = get_ch().query(sql, params)
    if not rows:
        return {"data": _generate_dummy_ph_trend(days), "note": "dummy ph trend"}
    return {"data": rows}


# ---------- 病害热力图 ----------

@router.get("/heatmap", tags=["Monitoring"])
async def get_heatmap_data(shelf_id: str):
    shelf_sql = "SELECT rows_count, cols_count FROM bookshelf_metadata WHERE shelf_id = {sid:String}"
    meta = get_ch().query_one(shelf_sql, {"sid": shelf_id})
    rows_c = int(meta["rows_count"]) if meta else 6
    cols_c = int(meta["cols_count"]) if meta else 8

    env_sql = """
        SELECT slot_id,
               avg(temperature) AS temp, avg(humidity) AS humi,
               avg(mold_spores) AS mold, max(active_mold) AS active_mold,
               avg(light_lux)   AS light
        FROM env_sensor_data
        WHERE shelf_id = {sid:String}
          AND timestamp >= now() - INTERVAL 24 HOUR
        GROUP BY slot_id
    """
    env_rows = {r["slot_id"]: r for r in get_ch().query(env_sql, {"sid": shelf_id})}

    ph_sql = """
        SELECT slot_id, avg(ph_value) AS ph_avg, min(ph_value) AS ph_min
        FROM ph_sensor_data
        WHERE shelf_id = {sid:String}
          AND timestamp >= now() - INTERVAL 7 DAY
        GROUP BY slot_id
    """
    ph_rows = {r["slot_id"]: r for r in get_ch().query(ph_sql, {"sid": shelf_id})}

    slot_list = _generate_dummy_slots(shelf_id)
    slot_paper_types = {}
    try:
        pt_sql = "SELECT slot_id, paper_type FROM book_slot_metadata WHERE shelf_id = {sid:String}"
        pt_rows = get_ch().query(pt_sql, {"sid": shelf_id})
        slot_paper_types = {r["slot_id"]: r.get("paper_type", "default") for r in pt_rows}
    except Exception:
        pass

    data = []
    for slot in slot_list:
        sid = slot["slot_id"]
        env = env_rows.get(sid, {})
        ph = ph_rows.get(sid, {})
        temp = float(env.get("temp") if env.get("temp") is not None else round(20 + (hash(sid) % 100) / 20, 2))
        humi = float(env.get("humi") if env.get("humi") is not None else round(45 + (hash(sid + "h") % 100) / 4, 2))
        mold = float(env.get("mold") if env.get("mold") is not None else 100 + (hash(sid + "m") % 500))
        active = int(env.get("active_mold") if env.get("active_mold") is not None else 0)
        light = float(env.get("light") if env.get("light") is not None else 10 + (hash(sid + "l") % 300) / 10)
        ph_val = float(ph.get("ph_avg") if ph.get("ph_avg") is not None else round(6.8 - (hash(sid + "p") % 250) / 100, 2))

        paper_type = slot_paper_types.get(sid, slot.get("paper_type", "default"))
        book_age = _estimate_book_age(slot.get("book_dynasty", ""), sid)

        mold_risk = mold_growth_model.evaluate(temp, humi, 72, mold, active)
        aging = paper_aging_model.full_prediction(ph_val, temp, humi, 0.5, book_age, paper_type)

        acid_score = max(0.0, min(1.0, (7.0 - ph_val) / 2.5))
        mold_score = mold_risk.mold_risk_index
        insect_score = mold_risk.insect_risk_index
        overall = max(acid_score, mold_score, insect_score)
        if overall < 0.25:
            level = "SAFE"
        elif overall < 0.5:
            level = "LOW"
        elif overall < 0.75:
            level = "MEDIUM"
        else:
            level = "HIGH"

        data.append({
            "slot_id": sid,
            "row_num": slot["row_num"],
            "col_num": slot["col_num"],
            "book_title": slot["book_title"],
            "book_dynasty": slot["book_dynasty"],
            "book_type": slot["book_type"],
            "sensor_env_id": slot["sensor_env_id"],
            "sensor_ph_id": slot["sensor_ph_id"],
            "metrics": {
                "temperature": round(temp, 2),
                "humidity": round(humi, 2),
                "ph": round(ph_val, 2),
                "mold_spores": round(mold, 0),
                "active_mold": active,
                "light_lux": round(light, 1),
            },
            "scores": {
                "acidosis": round(acid_score, 3),
                "mold": round(mold_score, 3),
                "insect": round(insect_score, 3),
                "overall": round(overall, 3),
                "level": level,
            },
            "prediction": {
                "ph_30d": aging.ph_30d,
                "ph_90d": aging.ph_90d,
                "aging_rate": aging.aging_rate_per_year,
                "life_expectancy": aging.life_expectancy_years,
                "risk_level": aging.risk_level,
                "mold_species": mold_risk.mold_species,
                "paper_type": paper_type,
                "activation_energy_kj": aging.activation_energy_kj,
            },
        })
    return {
        "shelf_id": shelf_id,
        "rows": rows_c,
        "cols": cols_c,
        "data": data,
    }


# ---------- 预测算法 ----------

@router.get("/predict/activation-energy-table", tags=["Prediction"])
async def get_activation_energy_table():
    return {"data": paper_aging_model.get_activation_energy_table()}


@router.post("/predict/paper-aging", tags=["Prediction"])
async def predict_paper_aging(req: PredictionRequest):
    result = paper_aging_model.full_prediction(
        initial_ph=req.initial_ph,
        avg_temp_c=req.avg_temp_c,
        avg_rh=req.avg_rh,
        avg_voc_ppm=req.avg_voc_ppm,
        book_age_years=req.book_age_years,
        paper_type=req.paper_type,
    )
    return {
        "slot_id": req.slot_id,
        "params": req.model_dump(),
        "result": {
            "ph_current": result.ph_current,
            "ph_30d": result.ph_30d,
            "ph_90d": result.ph_90d,
            "ph_180d": result.ph_180d,
            "ph_365d": result.ph_365d,
            "aging_rate_per_year": result.aging_rate_per_year,
            "dp_current": result.dp_current,
            "dp_365d": result.dp_365d,
            "life_expectancy_years": result.life_expectancy_years,
            "risk_level": result.risk_level,
            "paper_type": result.paper_type,
            "activation_energy_kj": result.activation_energy_kj,
        }
    }


@router.get("/predict/mold", tags=["Prediction"])
async def predict_mold(
    temp_c: float = 22.0,
    rh_percent: float = 55.0,
    exposure_hours: float = 72.0,
    spore_concentration: float = 300.0,
    voc_ppm: float = 0.5,
):
    r = mold_growth_model.evaluate(
        temp_c=temp_c, rh_percent=rh_percent,
        exposure_hours=exposure_hours,
        spore_concentration=spore_concentration,
        voc_ppm=voc_ppm,
    )
    return {
        "params": {
            "temperature_c": temp_c, "rh_percent": rh_percent,
            "exposure_hours": exposure_hours, "spore_concentration": spore_concentration,
        },
        "result": {
            "mold_risk_index": r.mold_risk_index,
            "mold_growth_rate": r.mold_growth_rate,
            "germination_likelihood": r.germination_likelihood,
            "mycelium_coverage_days": r.mycelium_coverage_days,
            "spore_production_risk": r.spore_production_risk,
            "active_mold_risk": r.active_mold_risk,
            "insect_risk_index": r.insect_risk_index,
            "susceptible_species": r.mold_species,
        }
    }


# ---------- 告警 ----------

@router.get("/alerts", tags=["Alerts"])
async def list_alerts(
    level: Optional[str] = None,
    shelf_id: Optional[str] = None,
    hours: int = Query(24, ge=1, le=24 * 30),
    only_unack: bool = False,
    limit: int = Query(200, ge=1, le=1000),
):
    start_ts = datetime.now(timezone.utc) - timedelta(hours=hours)
    where = ["timestamp >= {start:DateTime64(3)}"]
    params = {"start": int(start_ts.timestamp() * 1000)}
    if level:
        where.append("alert_level = {lv:String}")
        params["lv"] = level.upper()
    if shelf_id:
        where.append("shelf_id = {sid:String}")
        params["sid"] = shelf_id
    if only_unack:
        where.append("is_acknowledged = 0")
    sql = f"""
        SELECT * FROM alert_events
        WHERE {' AND '.join(where)}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """
    rows = get_ch().query(sql, params)
    return {"count": len(rows), "data": rows}


@router.post("/alerts/acknowledge", tags=["Alerts"])
async def acknowledge_alert(req: AlertAckRequest):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    sql = """
        ALTER TABLE alert_events
        UPDATE is_acknowledged = 1, ack_user = {usr:String}, ack_time = {ts:Int64}
        WHERE event_id = {eid:String}
    """
    try:
        get_ch().execute(sql, {"eid": req.event_id, "usr": req.ack_user, "ts": now_ms})
        return {"ok": True, "event_id": req.event_id, "ack_user": req.ack_user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts/stats", tags=["Alerts"])
async def alert_stats(days: int = Query(7, ge=1, le=90)):
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    sql = """
        SELECT
            alert_level,
            alert_type,
            count()    AS cnt,
            countIf(is_acknowledged = 0) AS unack_cnt
        FROM alert_events
        WHERE timestamp >= {start:DateTime64(3)}
        GROUP BY alert_level, alert_type
        ORDER BY alert_level, alert_type
    """
    rows = get_ch().query(sql, {"start": int(start_date.timestamp() * 1000)})
    return {"days": days, "data": rows}


# ---------- 知识图谱 & 药材推荐 ----------

@router.post("/herbs/recommend", tags=["Knowledge Graph"])
async def herb_recommendation(req: HerbRecommendRequest):
    result = knowledge_graph.recommend_herbs(
        disease_types=req.disease_types,
        mold_risk=req.mold_risk,
        insect_risk=req.insect_risk,
        ph_value=req.ph_value,
        top_k=req.top_k,
        book_dynasty=req.book_dynasty,
    )
    return result


@router.get("/herbs", tags=["Knowledge Graph"])
async def list_herbs():
    return {"data": knowledge_graph.get_all_herbs()}


@router.get("/herbs/graph", tags=["Knowledge Graph"])
async def herb_graph():
    return knowledge_graph.get_herb_graph()


# ---------- 统计概览 ----------

@router.get("/overview/stats", tags=["Overview"])
async def overview_stats():
    try:
        total_books_sql = "SELECT sum(book_count) AS total FROM book_slot_metadata"
        r = get_ch().query_one(total_books_sql)
        total_books = int(r["total"]) if r and r.get("total") else 30000

        shelf_sql = "SELECT count() AS cnt FROM bookshelf_metadata"
        r = get_ch().query_one(shelf_sql)
        total_shelves = int(r["cnt"]) if r else 7

        alert_sql = """
            SELECT
                countIf(alert_level='RED')    AS red,
                countIf(alert_level='ORANGE') AS orange,
                countIf(alert_level='YELLOW') AS yellow,
                countIf(is_acknowledged=0)    AS unack
            FROM alert_events
            WHERE timestamp >= now() - INTERVAL 24 HOUR
        """
        alert = get_ch().query_one(alert_sql) or {}

        avg_sql = """
            SELECT
                avg(temperature) AS t, avg(humidity) AS h, avg(ph_value) AS p, avg(mold_spores) AS m
            FROM env_sensor_data, ph_sensor_data
            WHERE env_sensor_data.timestamp >= now() - INTERVAL 1 HOUR
              AND ph_sensor_data.timestamp >= now() - INTERVAL 1 DAY
            LIMIT 1 BY 1
        """
        try:
            avgs = get_ch().query_one(avg_sql) or {}
        except Exception:
            avgs = {}

        return {
            "total_books": total_books,
            "total_shelves": total_shelves,
            "total_env_sensors": settings.sensor_count_env,
            "total_ph_sensors": settings.sensor_count_ph,
            "alerts_24h": {
                "red": int(alert.get("red", 0)),
                "orange": int(alert.get("orange", 0)),
                "yellow": int(alert.get("yellow", 0)),
                "unacknowledged": int(alert.get("unack", 0)),
            },
            "realtime_avg": {
                "temperature_c": round(float(avgs.get("t") or 21.5), 2),
                "humidity_percent": round(float(avgs.get("h") or 48.0), 2),
                "ph": round(float(avgs.get("p") or 6.6), 2),
                "mold_spores_cfu": round(float(avgs.get("m") or 280.0), 0),
            }
        }
    except Exception as e:
        logger.warning(f"Overview stats fallback: {e}")
        return {
            "total_books": 30000,
            "total_shelves": 7,
            "total_env_sensors": 50,
            "total_ph_sensors": 20,
            "alerts_24h": {"red": 0, "orange": 2, "yellow": 5, "unacknowledged": 3},
            "realtime_avg": {
                "temperature_c": 21.5,
                "humidity_percent": 48.0,
                "ph": 6.6,
                "mold_spores_cfu": 280,
            }
        }


# ---------- 辅助：生成无数据时的演示数据 ----------

def _generate_dummy_env(shelf_id=None) -> List[Dict]:
    import random
    random.seed(42)
    shelves = ["SH-A-01", "SH-A-02", "SH-A-03", "SH-B-01", "SH-B-02", "SH-C-01", "SH-C-02"]
    target = [shelf_id] if shelf_id else shelves
    rows = []
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    for sid in target:
        for i in range(1, 8):
            sensor_id = f"ENV-{(hash(sid) % 50) + i:03d}"
            temp_anomaly = 0
            mold_anomaly = 1
            if (hash(sid) % 7) + i == 5:
                temp_anomaly = 8
                mold_anomaly = 5
            rows.append({
                "timestamp": ts, "sensor_id": sensor_id,
                "shelf_id": sid, "slot_id": f"{sid}-R0{(i % 6) + 1}-C0{(i % 8) + 1}",
                "temperature": round(20 + random.random() * 5 + temp_anomaly, 2),
                "humidity": round(42 + random.random() * 18, 2),
                "light_lux": round(random.random() * 80, 1),
                "voc_ppm": round(random.random() * 1.5, 3),
                "mold_spores": round(80 + random.random() * 800 * mold_anomaly, 0),
                "active_mold": 1 if (hash(sid) % 11) == 3 and i == 2 else 0,
                "rssi": -55 - random.randint(0, 30),
            })
    return rows


def _generate_dummy_trend(hours: int, granularity: str) -> List[Dict]:
    import random
    random.seed(7)
    step_minutes = 5
    if "hour" in granularity: step_minutes = 60
    if "day" in granularity: step_minutes = 60 * 24
    points = min(hours * 60 // step_minutes, 3000)
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    base_temp = 21.0
    base_humi = 48.0
    base_mold = 200
    data = []
    for i in range(points):
        ts = start + timedelta(minutes=i * step_minutes)
        diurnal = math.sin(2 * math.pi * (i * step_minutes) / (24 * 60))
        temp = base_temp + diurnal * 2.5 + random.gauss(0, 0.3)
        humi = base_humi - diurnal * 4 + random.gauss(0, 1.0)
        mold = base_mold + diurnal * 80 + random.gauss(0, 30)
        data.append({
            "ts_bucket": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "temp_avg": round(temp, 3),
            "temp_max": round(temp + 0.6, 3),
            "temp_min": round(temp - 0.6, 3),
            "humi_avg": round(humi, 2),
            "humi_max": round(humi + 2, 2),
            "humi_min": round(humi - 2, 2),
            "light_avg": round(max(0, 25 + diurnal * 20 + random.gauss(0, 5)), 2),
            "light_max": round(max(0, 45 + diurnal * 25), 2),
            "voc_avg": round(0.3 + random.random() * 0.8, 3),
            "mold_avg": round(max(0, mold), 1),
            "active_mold_cnt": 1 if random.random() < 0.002 else 0,
        })
    return data


def _generate_dummy_ph(shelf_id=None, slot_id=None) -> List[Dict]:
    import random
    random.seed(11)
    shelves = ["SH-A-01"] if shelf_id else ["SH-A-01", "SH-A-02"]
    rows = []
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    idx = 0
    for sid in shelves:
        for r in range(1, 7):
            for c in range(1, 9):
                slid = f"{sid}-R{r:02d}-C{c:02d}"
                if slot_id and slid != slot_id:
                    continue
                trend = 0.0
                if (r, c) in [(2, 4), (3, 5)]:
                    trend = -1.3
                ph = round(7.0 + trend + random.gauss(0, 0.15), 3)
                rows.append({
                    "timestamp": ts,
                    "sensor_id": f"PH-{(idx % 20) + 1:03d}",
                    "shelf_id": sid,
                    "slot_id": slid,
                    "ph_value": max(4.2, ph),
                    "paper_cond": "GOOD" if ph >= 6.8 else "FAIR" if ph >= 6.2 else "POOR",
                    "rssi": -60 - random.randint(0, 20),
                })
                idx += 1
    return rows


def _generate_dummy_ph_trend(days: int) -> List[Dict]:
    import random
    random.seed(13)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    data = []
    ph = 6.9
    for i in range(days):
        d = start + timedelta(days=i)
        ph -= random.gauss(0.0025, 0.006)
        ph = max(4.5, min(7.5, ph))
        jitter = random.gauss(0, 0.04)
        data.append({
            "day": d.strftime("%Y-%m-%d"),
            "ph_avg": round(ph + jitter, 4),
            "ph_min": round(ph - 0.15 + jitter, 4),
            "ph_max": round(ph + 0.15 + jitter, 4),
            "samples": 288,
        })
    return data
