import math
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class PaperAgingResult:
    ph_current: float
    ph_30d: float
    ph_90d: float
    ph_180d: float
    ph_365d: float
    aging_rate_per_year: float
    dp_current: float
    dp_365d: float
    life_expectancy_years: float
    risk_level: str
    paper_type: str
    activation_energy_kj: float


class PaperAgingModel:
    R = 8.314
    T_REF = 295.0
    A = 1e13
    BASE_PH_DECLINE_RATE = 0.02
    DP_END_OF_LIFE = 200

    ACTIVATION_ENERGIES = {
        "bamboo": 78.0,
        "bark": 85.0,
        "xuan": 95.0,
        "hemp": 100.0,
        "straw": 76.0,
        "cotton": 90.0,
        "mixed": 85.0,
        "default": 85.0,
    }
    DEFAULT_EA = 85.0

    PAPER_TYPE_FACTORS = {
        "bamboo": 1.20,
        "bark": 1.00,
        "xuan": 0.80,
        "hemp": 1.10,
        "straw": 1.25,
        "cotton": 0.90,
        "mixed": 1.10,
        "default": 1.10,
    }
    DEFAULT_PAPER_TYPE_FACTOR = 1.10

    PAPER_TYPE_NAME_MAP = {
        "竹纸": "bamboo", "竹": "bamboo", "毛竹纸": "bamboo", "bamboo": "bamboo", "zhu": "bamboo", "zhuzhi": "bamboo",
        "皮纸": "bark", "皮": "bark", "楮皮纸": "bark", "桑皮纸": "bark", "构皮纸": "bark", "bark": "bark", "pi": "bark", "pizhi": "bark",
        "宣纸": "xuan", "宣": "xuan", "泾县纸": "xuan", "xuan": "xuan", "xuanzhi": "xuan",
        "麻纸": "hemp", "麻": "hemp", "苎麻纸": "hemp", "大麻纸": "hemp", "hemp": "hemp", "ma": "hemp", "mazhi": "hemp",
        "草纸": "straw", "稻草纸": "straw", "麦秆纸": "straw", "straw": "straw", "cao": "straw",
        "棉纸": "cotton", "棉": "cotton", "棉料纸": "cotton", "cotton": "cotton", "mian": "cotton",
        "混合纸": "mixed", "混料纸": "mixed", "竹棉混合": "mixed", "皮麻混合": "mixed", "mixed": "mixed",
        "default": "default", "": "default", "unknown": "default", None: "default",
    }

    PAPER_TYPE_DISPLAY_NAMES = {
        "bamboo": "竹纸", "bark": "皮纸", "xuan": "宣纸",
        "hemp": "麻纸", "straw": "草纸", "cotton": "棉纸",
        "mixed": "混合纸", "default": "默认/未标注",
    }

    def _normalize_paper_type(self, paper_type: str) -> str:
        if not paper_type:
            return "mixed"
        key = str(paper_type).strip().lower()
        if key in self.ACTIVATION_ENERGIES:
            return key
        return self.PAPER_TYPE_NAME_MAP.get(key, self.PAPER_TYPE_NAME_MAP.get(str(paper_type).strip(), "mixed"))

    def _get_ea(self, paper_type: str) -> float:
        norm = self._normalize_paper_type(paper_type)
        return self.ACTIVATION_ENERGIES.get(norm, self.DEFAULT_EA)

    def _get_paper_type_factor(self, paper_type: str) -> float:
        norm = self._normalize_paper_type(paper_type)
        return self.PAPER_TYPE_FACTORS.get(norm, self.DEFAULT_PAPER_TYPE_FACTOR)

    def _arrhenius_ratio(self, ea_kj: float, temp_c: float) -> float:
        ea_j = ea_kj * 1000.0
        t_kelvin = temp_c + 273.15
        k_t = self.A * math.exp(-ea_j / (self.R * t_kelvin))
        k_ref = self.A * math.exp(-ea_j / (self.R * self.T_REF))
        return k_t / k_ref

    def _humidity_factor(self, rh: float) -> float:
        if rh > 50.0:
            return math.exp(0.05 * (rh - 50.0))
        return 1.0

    def _voc_factor(self, voc_ppm: float) -> float:
        return 1.0 + 0.1 * voc_ppm

    def _compute_ph_decline_rate(self, ea_kj: float, temp_c: float, rh: float, voc_ppm: float, paper_type: str) -> float:
        arrhenius_ratio = self._arrhenius_ratio(ea_kj, temp_c)
        hum_factor = self._humidity_factor(rh)
        voc_f = self._voc_factor(voc_ppm)
        paper_factor = self._get_paper_type_factor(paper_type)
        return self.BASE_PH_DECLINE_RATE * arrhenius_ratio * hum_factor * voc_f * paper_factor

    def _compute_dp(self, ph: float, age_years: float) -> float:
        return 1000.0 * math.exp(-0.15 * (7.0 - ph)) * math.exp(-age_years * 0.001)

    def _compute_life_expectancy(self, ph_current: float, dp_current: float, ph_decline_rate: float, age_years: float) -> float:
        if dp_current <= self.DP_END_OF_LIFE:
            return 0.0
        if ph_decline_rate <= 0.0:
            return float("inf")
        dp_rate = dp_current * 0.15 * ph_decline_rate
        if dp_rate <= 0.0:
            return float("inf")
        log_ratio = math.log(dp_current / self.DP_END_OF_LIFE)
        if log_ratio <= 0.0:
            return 0.0
        return log_ratio / dp_rate

    def _determine_risk_level(self, ph_current: float, life_years: float) -> str:
        if ph_current < 5.0 or life_years <= 5.0:
            return "CRITICAL"
        if ph_current >= 5.0 and (ph_current < 5.5 or life_years <= 15.0):
            return "HIGH"
        if ph_current >= 5.5 and (ph_current < 6.0 or life_years <= 30.0):
            return "MEDIUM"
        if ph_current >= 6.0 and (ph_current < 6.5 or life_years <= 50.0):
            return "LOW"
        return "SAFE"

    def full_prediction(
        self,
        initial_ph: float,
        avg_temp_c: float,
        avg_rh: float,
        avg_voc_ppm: float,
        book_age_years: float,
        paper_type: str,
    ) -> PaperAgingResult:
        ea_kj = self._get_ea(paper_type)
        ph_decline_rate = self._compute_ph_decline_rate(ea_kj, avg_temp_c, avg_rh, avg_voc_ppm, paper_type)

        ph_30d = initial_ph - ph_decline_rate * (30.0 / 365.0)
        ph_90d = initial_ph - ph_decline_rate * (90.0 / 365.0)
        ph_180d = initial_ph - ph_decline_rate * (180.0 / 365.0)
        ph_365d = initial_ph - ph_decline_rate * 1.0

        dp_current = self._compute_dp(initial_ph, book_age_years)
        dp_365d = self._compute_dp(ph_365d, book_age_years + 1.0)

        dp_decline_rate = dp_current * 0.15 * ph_decline_rate

        life_expectancy = self._compute_life_expectancy(initial_ph, dp_current, ph_decline_rate, book_age_years)

        risk_level = self._determine_risk_level(initial_ph, life_expectancy)

        return PaperAgingResult(
            ph_current=initial_ph,
            ph_30d=ph_30d,
            ph_90d=ph_90d,
            ph_180d=ph_180d,
            ph_365d=ph_365d,
            aging_rate_per_year=ph_decline_rate,
            dp_current=dp_current,
            dp_365d=dp_365d,
            life_expectancy_years=life_expectancy,
            risk_level=risk_level,
            paper_type=paper_type,
            activation_energy_kj=ea_kj,
        )


paper_aging_model = PaperAgingModel()
