import math
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Optional

from ..core.config import config


class ArrheniusAgingModel:
    """
    纸张老化动力学模型 - 基于Arrhenius方程
    纸张纤维素降解速率与温度、湿度的关系
    所有参数从config.yaml加载，不再硬编码
    """

    def __init__(self, paper_type: str = "bamboo"):
        arr_config = config.get_arrhenius_config()

        self.R = arr_config.get("R", 8.314)
        self.A = arr_config.get("A", 1.0e10)
        self.pH_DECAY_RATE_REF = arr_config.get("pH_decay_rate_ref", 0.005)
        self.REF_TEMP = arr_config.get("ref_temp", 298.15)
        self.REF_HUMIDITY = arr_config.get("ref_humidity", 50.0)

        self.paper_type_map = arr_config.get("paper_type_map", {})
        self.paper_types = arr_config.get("paper_types", {})

        self.paper_type_key = self._normalize_paper_type(paper_type)
        if self.paper_type_key not in self.paper_types:
            self.paper_type_key = "bamboo"

        self.paper_type = paper_type
        self._set_paper_parameters()

    def _normalize_paper_type(self, paper_type: str) -> str:
        """将中文纸张名称映射为内部key"""
        return self.paper_type_map.get(paper_type, paper_type)

    def _set_paper_parameters(self):
        """
        根据纸张类型设置动力学参数
        活化能 Ea (kJ/mol) 是影响老化速率的关键参数：
        - Ea越低，温度对老化速率的影响越敏感
        - 竹纸半纤维素含量高 → Ea低 → 易老化
        - 皮纸纤维素纯度高 → Ea高 → 更耐久
        """
        p = self.paper_types.get(self.paper_type_key, self.paper_types.get("bamboo", {}))
        self.initial_ph = p.get("ph0", 6.5)
        self.Ea = p.get("Ea", 78.0)
        self.k_factor = p.get("k_factor", 1.0)
        self.strength_factor = p.get("strength_factor", 1.0)
        self.display_name = p.get("name", "竹纸")

    def arrhenius_rate(self, temperature_c: float) -> float:
        """
        计算Arrhenius速率常数
        k = A * exp(-Ea / (R * T))

        其中Ea为纸张特定的活化能，已在初始化时根据paper_type设置
        """
        T_kelvin = temperature_c + 273.15
        k = self.A * math.exp(-self.Ea * 1000 / (self.R * T_kelvin))
        return k

    def humidity_factor(self, humidity: float) -> float:
        """
        湿度影响因子
        高湿度加速水解反应
        """
        if humidity <= 0:
            humidity = 1
        h_factor = math.pow(humidity / self.REF_HUMIDITY, 1.5)
        return h_factor

    def ph_decay_rate(self, temperature_c: float, humidity: float, current_ph: float = None) -> float:
        """
        计算pH下降速率 (每年pH下降量)
        综合考虑温度、湿度和自催化效应
        """
        if current_ph is None:
            current_ph = self.initial_ph

        k_ref = self.pH_DECAY_RATE_REF * self.k_factor
        k_temp = self.arrhenius_rate(temperature_c) / self.arrhenius_rate(self.REF_TEMP - 273.15)
        k_humid = self.humidity_factor(humidity)

        autocatalytic_factor = math.pow(10, -0.1 * (current_ph - 7.0))

        decay_rate = k_ref * k_temp * k_humid * autocatalytic_factor
        return decay_rate

    def predict_ph(self, initial_ph: float, temperature_c: float, humidity: float,
                   days: int, temperature_history: List[Tuple[float, float]] = None) -> float:
        """
        预测未来某一天的pH值
        使用积分近似计算pH变化
        """
        if temperature_history is None:
            avg_temp = temperature_c
            avg_humid = humidity
        else:
            total_temp = sum(t for t, _ in temperature_history)
            total_humid = sum(h for _, h in temperature_history)
            n = len(temperature_history)
            avg_temp = total_temp / n if n > 0 else temperature_c
            avg_humid = total_humid / n if n > 0 else humidity

        current_ph = initial_ph
        total_days = days
        step_days = 1
        steps = total_days // step_days

        for _ in range(steps):
            decay_rate = self.ph_decay_rate(avg_temp, avg_humid, current_ph)
            ph_change = decay_rate * (step_days / 365.0)
            current_ph -= ph_change
            if current_ph < 3.0:
                current_ph = 3.0
                break

        return round(current_ph, 3)

    def predict_ph_multiple(self, initial_ph: float, temperature_c: float, humidity: float,
                            days_list: List[int]) -> Dict[int, float]:
        """
        预测多个时间点的pH值
        """
        results = {}
        current_ph = initial_ph
        prev_days = 0

        for days in sorted(days_list):
            delta_days = days - prev_days
            current_ph = self.predict_ph(current_ph, temperature_c, humidity, delta_days)
            results[days] = current_ph
            prev_days = days

        return results

    def aging_index(self, temperature_c: float, humidity: float, current_ph: float) -> Dict[str, float]:
        """
        计算老化指数
        返回多个老化相关指标
        """
        decay_rate = self.ph_decay_rate(temperature_c, humidity, current_ph)
        remaining_life_years = max(0, (current_ph - 4.5) / decay_rate) if decay_rate > 0 else 100.0
        strength_retention = math.exp(-decay_rate * 10 / self.strength_factor)
        brittleness_index = max(0, 1.0 - strength_retention)

        return {
            "ph_decay_rate_per_year": round(decay_rate, 4),
            "predicted_lifetime_years": round(remaining_life_years, 1),
            "strength_retention_10y_pct": round(strength_retention * 100, 2),
            "brittleness_index": round(brittleness_index, 4),
            "aging_severity": self._severity_level(current_ph, decay_rate)
        }

    def _severity_level(self, current_ph: float, decay_rate: float) -> str:
        if current_ph < 5.5 or decay_rate > 0.05:
            return "critical"
        elif current_ph < 6.0 or decay_rate > 0.02:
            return "warning"
        elif current_ph < 6.5 or decay_rate > 0.01:
            return "caution"
        else:
            return "normal"

    def daily_ph_history(self, initial_ph: float, start_date: str,
                         temperature_c: float, humidity: float, days: int) -> List[Dict]:
        """
        生成每日pH历史/预测数据
        """
        history = []
        current_ph = initial_ph
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")

        for day in range(days + 1):
            date = start_dt + timedelta(days=day)
            decay_rate = self.ph_decay_rate(temperature_c, humidity, current_ph)
            aging_info = self.aging_index(temperature_c, humidity, current_ph)

            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "ph_value": round(current_ph, 3),
                "decay_rate": round(decay_rate, 4),
                "aging_severity": aging_info["aging_severity"]
            })

            ph_change = decay_rate * (1 / 365.0)
            current_ph -= ph_change
            if current_ph < 3.0:
                current_ph = 3.0

        return history
