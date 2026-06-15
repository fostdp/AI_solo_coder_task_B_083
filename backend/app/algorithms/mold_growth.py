import math
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Optional


class MoldGrowthModel:
    """
    霉菌生长模型
    基于温度和相对湿度的响应函数
    参考霉菌生长预测模型（如MRTD、MMV模型）
    """

    MOLD_TYPES = {
        "aspergillus": {
            "name": "曲霉",
            "opt_temp": 25.0,
            "min_temp": 10.0,
            "max_temp": 45.0,
            "opt_humidity": 85.0,
            "min_humidity": 65.0,
            "growth_rate": 1.0,
            "spore_production": 0.8,
            "paper_damage": 0.6
        },
        "penicillium": {
            "name": "青霉",
            "opt_temp": 22.0,
            "min_temp": 5.0,
            "max_temp": 35.0,
            "opt_humidity": 80.0,
            "min_humidity": 70.0,
            "growth_rate": 0.8,
            "spore_production": 1.0,
            "paper_damage": 0.7
        },
        "chaetomium": {
            "name": "毛壳菌",
            "opt_temp": 28.0,
            "min_temp": 15.0,
            "max_temp": 40.0,
            "opt_humidity": 90.0,
            "min_humidity": 75.0,
            "growth_rate": 0.7,
            "spore_production": 0.6,
            "paper_damage": 1.0
        },
        "trichoderma": {
            "name": "木霉",
            "opt_temp": 27.0,
            "min_temp": 8.0,
            "max_temp": 38.0,
            "opt_humidity": 88.0,
            "min_humidity": 72.0,
            "growth_rate": 1.2,
            "spore_production": 0.9,
            "paper_damage": 0.8
        }
    }

    def __init__(self, mold_type: str = "mixed"):
        self.mold_type = mold_type
        self.params = self._get_params()

    def _get_params(self) -> Dict:
        if self.mold_type in self.MOLD_TYPES:
            return self.MOLD_TYPES[self.mold_type]
        else:
            return self._get_mixed_params()

    def _get_mixed_params(self) -> Dict:
        types = list(self.MOLD_TYPES.values())
        n = len(types)
        return {
            "name": "混合霉菌",
            "opt_temp": sum(t["opt_temp"] for t in types) / n,
            "min_temp": min(t["min_temp"] for t in types),
            "max_temp": max(t["max_temp"] for t in types),
            "opt_humidity": sum(t["opt_humidity"] for t in types) / n,
            "min_humidity": min(t["min_humidity"] for t in types),
            "growth_rate": sum(t["growth_rate"] for t in types) / n,
            "spore_production": sum(t["spore_production"] for t in types) / n,
            "paper_damage": sum(t["paper_damage"] for t in types) / n
        }

    def temperature_response(self, temperature_c: float) -> float:
        """
        温度响应函数（钟形曲线）
        返回0-1之间的值
        """
        if temperature_c <= self.params["min_temp"] or temperature_c >= self.params["max_temp"]:
            return 0.0

        opt = self.params["opt_temp"]
        min_t = self.params["min_temp"]
        max_t = self.params["max_temp"]

        if temperature_c <= opt:
            t_factor = math.pow((temperature_c - min_t) / (opt - min_t), 0.8)
        else:
            t_factor = math.pow((max_t - temperature_c) / (max_t - opt), 1.2)

        return max(0.0, min(1.0, t_factor))

    def humidity_response(self, humidity: float) -> float:
        """
        湿度响应函数（S型曲线）
        返回0-1之间的值
        """
        if humidity <= self.params["min_humidity"]:
            return 0.0
        if humidity >= 100:
            return 1.0

        min_h = self.params["min_humidity"]
        opt_h = self.params["opt_humidity"]
        humidity_range = opt_h - min_h

        if humidity_range <= 0:
            return 0.0

        if humidity <= opt_h:
            h_norm = (humidity - min_h) / humidity_range
            h_factor = 1.0 - math.exp(-3.0 * h_norm)
        else:
            h_factor = 1.0

        return max(0.0, min(1.0, h_factor))

    def growth_rate(self, temperature_c: float, humidity: float) -> float:
        """
        计算霉菌生长速率（相对单位/天）
        """
        t_resp = self.temperature_response(temperature_c)
        h_resp = self.humidity_response(humidity)

        interaction = t_resp * h_resp

        base_rate = self.params["growth_rate"]
        rate = base_rate * interaction

        return max(0.0, rate)

    def spore_concentration(self, temperature_c: float, humidity: float,
                            initial_spores: float = 10.0, days: float = 1.0) -> float:
        """
        预测霉菌孢子浓度 (CFU/m³)
        """
        rate = self.growth_rate(temperature_c, humidity)
        spore_factor = self.params["spore_production"]

        final_spores = initial_spores * math.exp(rate * spore_factor * days)

        return round(final_spores, 1)

    def mold_risk_index(self, temperature_c: float, humidity: float,
                        current_spores: float = None) -> Dict[str, float]:
        """
        计算霉菌风险指数
        """
        growth_rate = self.growth_rate(temperature_c, humidity)
        t_resp = self.temperature_response(temperature_c)
        h_resp = self.humidity_response(humidity)

        if current_spores is not None:
            predicted_7d = self.spore_concentration(temperature_c, humidity, current_spores, 7)
            predicted_30d = self.spore_concentration(temperature_c, humidity, current_spores, 30)
        else:
            baseline = 50.0
            predicted_7d = self.spore_concentration(temperature_c, humidity, baseline, 7)
            predicted_30d = self.spore_concentration(temperature_c, humidity, baseline, 30)

        risk_score = (t_resp * 0.3 + h_resp * 0.7) * 100

        if risk_score >= 80:
            risk_level = "high"
        elif risk_score >= 50:
            risk_level = "medium"
        elif risk_score >= 20:
            risk_level = "low"
        else:
            risk_level = "negligible"

        damage_potential = self.params["paper_damage"] * (risk_score / 100)

        return {
            "risk_score": round(risk_score, 2),
            "risk_level": risk_level,
            "growth_rate_per_day": round(growth_rate, 4),
            "predicted_spores_7d": predicted_7d,
            "predicted_spores_30d": predicted_30d,
            "paper_damage_potential": round(damage_potential, 4),
            "temperature_suitability": round(t_resp * 100, 1),
            "humidity_suitability": round(h_resp * 100, 1)
        }

    def is_active_mold(self, temperature_c: float, humidity: float,
                       spore_concentration: float = None) -> bool:
        """
        判断是否存在活性霉菌
        阈值：孢子浓度>1000 CFU/m³ 且温湿度条件适宜
        """
        if spore_concentration is not None and spore_concentration < 500:
            return False

        t_resp = self.temperature_response(temperature_c)
        h_resp = self.humidity_response(humidity)

        if t_resp > 0.3 and h_resp > 0.4:
            if spore_concentration and spore_concentration > 1000:
                return True
            if t_resp > 0.5 and h_resp > 0.6:
                return True

        return False

    def daily_growth_simulation(self, temperature_c: float, humidity: float,
                                initial_biomass: float = 0.01, days: int = 30) -> List[Dict]:
        """
        模拟每日霉菌生长情况
        """
        biomass = initial_biomass
        history = []
        spores = 10.0

        for day in range(days + 1):
            rate = self.growth_rate(temperature_c, humidity)
            risk = self.mold_risk_index(temperature_c, humidity, spores)

            history.append({
                "day": day,
                "biomass": round(biomass, 4),
                "spore_concentration": round(spores, 1),
                "growth_rate": round(rate, 4),
                "risk_level": risk["risk_level"],
                "risk_score": risk["risk_score"]
            })

            biomass = biomass * (1 + rate * 0.1)
            if biomass > 100:
                biomass = 100

            spores = self.spore_concentration(temperature_c, humidity, spores, 1)
            if spores > 100000:
                spores = 100000

        return history

    def optimal_conditions(self) -> Dict[str, float]:
        """
        返回霉菌最适宜生长条件
        """
        return {
            "optimal_temperature": self.params["opt_temp"],
            "optimal_humidity": self.params["opt_humidity"],
            "temperature_range": [self.params["min_temp"], self.params["max_temp"]],
            "min_humidity_for_growth": self.params["min_humidity"]
        }


def calculate_combined_risk(temperature: float, humidity: float, ph_value: float,
                            mold_spores: float = None) -> Dict[str, any]:
    """
    计算综合病害风险
    综合考虑酸化、霉变等因素
    """
    mold_model = MoldGrowthModel()
    aging_model = ArrheniusAgingModel()

    mold_risk = mold_model.mold_risk_index(temperature, humidity, mold_spores)
    aging_info = aging_model.aging_index(temperature, humidity, ph_value)

    acid_risk_score = max(0, (6.5 - ph_value) / 2.0 * 100) if ph_value < 6.5 else 0

    if acid_risk_score >= 80 or mold_risk["risk_score"] >= 80:
        overall_level = "critical"
    elif acid_risk_score >= 50 or mold_risk["risk_score"] >= 50:
        overall_level = "warning"
    elif acid_risk_score >= 20 or mold_risk["risk_score"] >= 20:
        overall_level = "caution"
    else:
        overall_level = "normal"

    overall_score = max(acid_risk_score, mold_risk["risk_score"])

    primary_risks = []
    if acid_risk_score >= 30:
        primary_risks.append("acidification")
    if mold_risk["risk_score"] >= 30:
        primary_risks.append("mold")

    return {
        "overall_risk_score": round(overall_score, 2),
        "overall_risk_level": overall_level,
        "primary_risks": primary_risks,
        "acidification_risk": {
            "score": round(acid_risk_score, 2),
            "current_ph": ph_value,
            "decay_rate": aging_info["ph_decay_rate_per_year"]
        },
        "mold_risk": mold_risk
    }
