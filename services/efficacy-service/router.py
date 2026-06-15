"""
efficacy-service 路由模块
包含药效评估相关的所有 API 端点
"""
import logging
import sys
import os
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend", "app"))

from efficacy_engine.efficacy import (
    bayesian_efficacy_estimation,
    fit_zero_inflated_poisson,
    detect_zero_inflation,
    ZIPResult,
    BayesianEfficacyResult,
)
from efficacy_engine.service import SporeDataCollector

logger = logging.getLogger(__name__)

router = APIRouter()

PRESCRIPTION_NAMES = {
    "yuncao": "芸草",
    "huangbo": "黄柏",
    "yanye": "烟叶",
}

VALID_PRESCRIPTIONS = ["yuncao", "huangbo", "yanye"]

TREATMENT_GROUP_SHELVES = {
    "yuncao": ["SHELF-03", "SHELF-04"],
    "huangbo": ["SHELF-05", "SHELF-06"],
    "yanye": ["SHELF-07", "SHELF-08"],
}

CONTROL_GROUP_SHELVES = ["SHELF-01", "SHELF-02"]

PRIOR_ALPHA = 2.0
PRIOR_BETA = 2.0
CI_LEVEL = 0.95
MIN_SAMPLE_SIZE = 10
RUN_INTERVAL = 3600


_data_collector = SporeDataCollector(lookback_hours=48)


def _get_efficacy_engine(request: Request):
    """从请求状态获取 EfficacyEngineService 实例"""
    try:
        services = request.app.state.services
        if hasattr(services, 'efficacy_engine') and services.efficacy_engine:
            return services.efficacy_engine
    except Exception:
        pass
    return None


def _serialize_zip_result(result: ZIPResult) -> Dict[str, Any]:
    """序列化 ZIPResult 为字典"""
    return {
        "pi": result.pi,
        "lambda_": result.lambda_,
        "log_likelihood": result.log_likelihood,
        "converged": result.converged,
        "iterations": result.iterations,
        "zero_inflation_ratio": result.zero_inflation_ratio,
    }


def _serialize_bayesian_result(result: BayesianEfficacyResult) -> Dict[str, Any]:
    """序列化 BayesianEfficacyResult 为字典"""
    return {
        "posterior_alpha": result.posterior_alpha,
        "posterior_beta": result.posterior_beta,
        "posterior_mean": result.posterior_mean,
        "posterior_var": result.posterior_var,
        "ci_low": result.ci_low,
        "ci_high": result.ci_high,
        "reduction_rate": result.reduction_rate,
        "sample_size": result.sample_size,
    }


@router.get("/evaluate/{prescription}")
async def evaluate_prescription(
    request: Request,
    prescription: str,
    shelf_id: Optional[str] = Query(None, description="指定书架ID"),
    slot_id: Optional[str] = Query(None, description="指定格口ID"),
):
    """
    评估单个药方的防霉效果
    
    Args:
        prescription: 药方名称 (yuncao, huangbo, yanye)
        shelf_id: 可选，指定书架ID
        slot_id: 可选，指定格口ID
    
    Returns:
        药效评估结果
    """
    if prescription not in VALID_PRESCRIPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"无效药方，可选: {', '.join(VALID_PRESCRIPTIONS)}"
        )
    
    engine = _get_efficacy_engine(request)
    if engine:
        result = await engine.evaluate_prescription(prescription, shelf_id, slot_id)
        if result:
            return result.to_dict()
        return JSONResponse(
            status_code=503,
            content={"error": "数据不足，无法评估"}
        )
    
    import time
    treatment_shelves = TREATMENT_GROUP_SHELVES.get(prescription, [])
    if not treatment_shelves:
        raise HTTPException(status_code=404, detail=f"药方 {prescription} 没有配置治疗组书架")
    
    reference_time = time.time() - RUN_INTERVAL
    
    if shelf_id and slot_id:
        treatment_data = _data_collector.get_before_after_data([shelf_id], reference_time)
    else:
        treatment_data = _data_collector.get_before_after_data(treatment_shelves, reference_time)
    
    control_data = _data_collector.get_before_after_data(CONTROL_GROUP_SHELVES, reference_time)
    
    sample_size = min(len(treatment_data), len(control_data))
    if sample_size < MIN_SAMPLE_SIZE:
        if treatment_data and control_data:
            sample_size = min(len(treatment_data), len(control_data))
            treatment_data = treatment_data[:sample_size]
            control_data = control_data[:sample_size]
        else:
            return JSONResponse(
                status_code=503,
                content={"error": "数据不足，无法评估"}
            )
    
    try:
        bayesian_result = bayesian_efficacy_estimation(
            treatment_data=treatment_data,
            control_data=control_data,
            prior_alpha=PRIOR_ALPHA,
            prior_beta=PRIOR_BETA,
            ci_level=CI_LEVEL,
        )
    except Exception as e:
        logger.error(f"贝叶斯评估失败 {prescription}: {e}")
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")
    
    spores_before = sum(d["spores_before"] for d in treatment_data) / len(treatment_data)
    spores_after = sum(d["spores_after"] for d in treatment_data) / len(treatment_data)
    
    if spores_before <= 0:
        reduction_rate = 0.0
    else:
        reduction_rate = max(0.0, min(1.0, (spores_before - spores_after) / spores_before))
    
    return {
        "prescription": prescription,
        "treatment_group": PRESCRIPTION_NAMES.get(prescription, prescription),
        "reduction_rate": reduction_rate,
        "efficacy_mean": bayesian_result.posterior_mean,
        "efficacy_ci_low": bayesian_result.ci_low,
        "efficacy_ci_high": bayesian_result.ci_high,
        "posterior_mean": bayesian_result.posterior_mean,
        "posterior_var": bayesian_result.posterior_var,
        "sample_size": sample_size,
        "spores_before": spores_before,
        "spores_after": spores_after,
        "bayesian_details": _serialize_bayesian_result(bayesian_result),
    }


@router.get("/evaluate_all")
async def evaluate_all_prescriptions(request: Request):
    """
    评估所有药方的防霉效果
    
    Returns:
        所有药方的评估结果列表
    """
    engine = _get_efficacy_engine(request)
    if engine:
        results = await engine.evaluate_all()
        return {"results": [r.to_dict() for r in results]}
    
    results = []
    for prescription in VALID_PRESCRIPTIONS:
        import time
        treatment_shelves = TREATMENT_GROUP_SHELVES.get(prescription, [])
        if not treatment_shelves:
            continue
        
        reference_time = time.time() - RUN_INTERVAL
        treatment_data = _data_collector.get_before_after_data(treatment_shelves, reference_time)
        control_data = _data_collector.get_before_after_data(CONTROL_GROUP_SHELVES, reference_time)
        
        sample_size = min(len(treatment_data), len(control_data))
        if sample_size < MIN_SAMPLE_SIZE:
            if treatment_data and control_data:
                sample_size = min(len(treatment_data), len(control_data))
                treatment_data = treatment_data[:sample_size]
                control_data = control_data[:sample_size]
            else:
                continue
        
        try:
            bayesian_result = bayesian_efficacy_estimation(
                treatment_data=treatment_data,
                control_data=control_data,
                prior_alpha=PRIOR_ALPHA,
                prior_beta=PRIOR_BETA,
                ci_level=CI_LEVEL,
            )
        except Exception as e:
            logger.error(f"贝叶斯评估失败 {prescription}: {e}")
            continue
        
        spores_before = sum(d["spores_before"] for d in treatment_data) / len(treatment_data)
        spores_after = sum(d["spores_after"] for d in treatment_data) / len(treatment_data)
        
        if spores_before <= 0:
            reduction_rate = 0.0
        else:
            reduction_rate = max(0.0, min(1.0, (spores_before - spores_after) / spores_before))
        
        results.append({
            "prescription": prescription,
            "treatment_group": PRESCRIPTION_NAMES.get(prescription, prescription),
            "reduction_rate": reduction_rate,
            "efficacy_mean": bayesian_result.posterior_mean,
            "efficacy_ci_low": bayesian_result.ci_low,
            "efficacy_ci_high": bayesian_result.ci_high,
            "posterior_mean": bayesian_result.posterior_mean,
            "posterior_var": bayesian_result.posterior_var,
            "sample_size": sample_size,
            "spores_before": spores_before,
            "spores_after": spores_after,
        })
    
    return {"results": results}


@router.get("/summary")
async def get_efficacy_summary(request: Request):
    """
    获取药效评估摘要
    
    Returns:
        药效评估摘要信息，包括统计数据、配置和各药方数据点信息
    """
    engine = _get_efficacy_engine(request)
    if engine:
        return engine.get_efficacy_summary()
    
    summary = {
        "stats": {
            "total_evaluations": 0,
            "total_errors": 0,
            "last_evaluation_time": None,
            "prescription_evaluations": {},
        },
        "prescriptions": {},
        "control_group": CONTROL_GROUP_SHELVES,
        "treatment_groups": TREATMENT_GROUP_SHELVES,
        "bayesian_prior": {
            "alpha": PRIOR_ALPHA,
            "beta": PRIOR_BETA,
        },
        "config": {
            "run_interval": RUN_INTERVAL,
            "min_sample_size": MIN_SAMPLE_SIZE,
            "ci_level": CI_LEVEL,
        },
    }
    
    for prescription in VALID_PRESCRIPTIONS:
        treatment_shelves = TREATMENT_GROUP_SHELVES.get(prescription, [])
        treatment_data = _data_collector.get_shelf_data(treatment_shelves)
        control_data = _data_collector.get_shelf_data(CONTROL_GROUP_SHELVES)
        
        summary["prescriptions"][prescription] = {
            "name": PRESCRIPTION_NAMES.get(prescription, prescription),
            "treatment_shelves": treatment_shelves,
            "treatment_data_points": len(treatment_data),
            "control_data_points": len(control_data),
        }
    
    return summary


@router.get("/zip/fit")
async def fit_zip_model(
    data: Optional[str] = Query(None, description="逗号分隔的整数数据列表，例如: 0,0,1,0,2,0,0"),
    generate_demo: bool = Query(False, description="是否生成演示数据进行拟合"),
):
    """
    拟合零膨胀泊松模型 (Zero-Inflated Poisson)
    
    使用 EM 算法拟合 ZIP 模型，用于处理含有大量零值的霉菌孢子数据。
    
    Args:
        data: 逗号分隔的整数数据列表
        generate_demo: 是否生成演示数据
    
    Returns:
        ZIP 模型拟合结果，包括 pi (零膨胀概率), lambda_ (泊松强度), 对数似然等
    """
    if data:
        try:
            data_list = [int(x.strip()) for x in data.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="数据格式错误，请提供逗号分隔的整数列表，例如: 0,0,1,0,2"
            )
    elif generate_demo:
        import random
        random.seed(42)
        data_list = []
        for _ in range(100):
            if random.random() < 0.6:
                data_list.append(0)
            else:
                data_list.append(random.poissonvariate(3))
    else:
        raise HTTPException(
            status_code=400,
            detail="请提供 data 参数或设置 generate_demo=true"
        )
    
    if not data_list:
        raise HTTPException(status_code=400, detail="数据不能为空")
    
    is_zi, zero_ratio = detect_zero_inflation(data_list)
    
    zip_result = fit_zero_inflated_poisson(data_list)
    
    response = {
        "input_data": data_list,
        "data_size": len(data_list),
        "zero_inflation_detected": is_zi,
        "zero_ratio": zero_ratio,
        "zip_result": _serialize_zip_result(zip_result),
        "model_description": {
            "formula": "P(Y=k) = π * I(k=0) + (1-π) * Poisson(k; λ)",
            "pi_interpretation": "结构零概率（数据中固有零值的比例）",
            "lambda_interpretation": "非零部分的泊松分布强度参数",
        },
    }
    
    return response


@router.post("/zip/fit")
async def fit_zip_model_post(
    request_data: Dict[str, Any],
):
    """
    POST 接口：拟合零膨胀泊松模型
    
    Args:
        request_data: 请求体，包含 data 字段（整数列表）
    
    Returns:
        ZIP 模型拟合结果
    """
    data_list = request_data.get("data", [])
    
    if not data_list:
        raise HTTPException(status_code=400, detail="数据不能为空")
    
    try:
        data_list = [int(x) for x in data_list]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="数据必须是整数列表")
    
    is_zi, zero_ratio = detect_zero_inflation(data_list)
    
    zip_result = fit_zero_inflated_poisson(data_list)
    
    return {
        "input_data": data_list,
        "data_size": len(data_list),
        "zero_inflation_detected": is_zi,
        "zero_ratio": zero_ratio,
        "zip_result": _serialize_zip_result(zip_result),
    }


@router.get("/zip/detect")
async def detect_zero_inflation_endpoint(
    data: str = Query(..., description="逗号分隔的数值列表"),
):
    """
    检测数据是否存在零膨胀
    
    Args:
        data: 逗号分隔的数值列表
    
    Returns:
        零膨胀检测结果
    """
    try:
        data_list = [float(x.strip()) for x in data.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="数据格式错误，请提供逗号分隔的数值列表"
        )
    
    if not data_list:
        raise HTTPException(status_code=400, detail="数据不能为空")
    
    is_zi, zero_ratio = detect_zero_inflation(data_list)
    
    return {
        "zero_inflation_detected": is_zi,
        "zero_ratio": zero_ratio,
        "data_size": len(data_list),
        "mean": sum(data_list) / len(data_list),
        "variance": sum((x - sum(data_list) / len(data_list)) ** 2 for x in data_list) / len(data_list),
    }
