"""
霉菌生长模型
基于温度和相对湿度的响应函数模型 (ISO 16000 / Skaar 曲线拟合)
同时包含虫蛀风险评估
"""
import math
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional


@dataclass
class MoldRiskResult:
    mold_risk_index: float
    mold_growth_rate: float
    germination_likelihood: float
    mycelium_coverage_days: Optional[float]
    spore_production_risk: float
    active_mold_risk: float
    insect_risk_index: float
    mold_species: List[str]


class MoldGrowthModel:

    def __init__(self):
        self.species_params = {
            "Aspergillus flavus": {"T_min": 12.0, "T_opt": 32.0, "T_max": 45.0,
                                   "RH_min": 0.82, "RH_opt": 0.95, "k": 0.85},
            "Aspergillus niger": {"T_min": 6.0, "T_opt": 30.0, "T_max": 47.0,
                                  "RH_min": 0.77, "RH_opt": 0.94, "k": 0.90},
            "Penicillium chrysogenum": {"T_min": 4.0, "T_opt": 26.0, "T_max": 38.0,
                                        "RH_min": 0.78, "RH_opt": 0.93, "k": 0.80},
            "Chaetomium globosum": {"T_min": 6.0, "T_opt": 28.0, "T_max": 38.0,
                                    "RH_min": 0.90, "RH_opt": 0.97, "k": 1.10},
            "Trichoderma viride": {"T_min": 5.0, "T_opt": 27.0, "T_max": 38.0,
                                   "RH_min": 0.85, "RH_opt": 0.96, "k": 0.95},
        }

    def _temp_response(self, T: float, T_min: float, T_opt: float, T_max: float) -> float:
        if T <= T_min or T >= T_max:
            return 0.0
        if T <= T_opt:
            x = (T - T_min) / (T_opt - T_min) if T_opt > T_min else 1.0
            return math.sin(math.pi * x / 2)
        else:
            x = (T_max - T) / (T_max - T_opt) if T_max > T_opt else 1.0
            return math.sin(math.pi * x / 2 + math.pi / 2) * 0.7 + 0.3

    def _rh_response(self, RH_frac: float, RH_min: float, RH_opt: float) -> float:
        if RH_frac < RH_min:
            return 0.0
        if RH_frac >= RH_opt:
            return 1.0
        normalized = (RH_frac - RH_min) / (RH_opt - RH_min)
        return 1.0 - math.exp(-4.0 * normalized)

    def _time_factor(self, exposure_hours: float) -> float:
        return 1.0 - math.exp(-exposure_hours / 48.0)

    def _single_species_risk(
        self,
        temp_c: float,
        rh_percent: float,
        exposure_hours: float,
        params: Dict,
    ) -> Tuple[float, float, float]:
        RH = rh_percent / 100.0
        f_T = self._temp_response(temp_c, params["T_min"], params["T_opt"], params["T_max"])
        f_RH = self._rh_response(RH, params["RH_min"], params["RH_opt"])
        f_t = self._time_factor(exposure_hours)
        germination = f_T * f_RH * f_t
        growth_rate = params["k"] * f_T * f_RH
        spore_risk = germination * (0.5 + 0.5 * f_t) if germination > 0.3 else 0.0
        return germination, growth_rate, spore_risk

    def evaluate(
        self,
        temp_c: float,
        rh_percent: float,
        exposure_hours: float = 72.0,
        spore_concentration: float = 0.0,
        active_mold_detected: int = 0,
        voc_ppm: float = 0.0,
    ) -> MoldRiskResult:
        species_risks: Dict[str, float] = {}
        total_germination = 0.0
        total_growth_rate = 0.0
        total_spore_risk = 0.0
        active_species: List[str] = []

        for name, params in self.species_params.items():
            germ, growth, spore = self._single_species_risk(
                temp_c, rh_percent, exposure_hours, params
            )
            species_risks[name] = germ
            total_germination += germ
            total_growth_rate += growth
            total_spore_risk += spore
            if germ > 0.3:
                active_species.append(name)

        n_species = len(self.species_params)
        avg_germination = total_germination / n_species
        avg_growth = total_growth_rate / n_species
        avg_spore = total_spore_risk / n_species

        f_spore = 1.0 + (spore_concentration / 1000.0) * 0.6
        f_voc = 1.0 + voc_ppm * 0.1
        mold_risk = min(1.0, avg_germination * f_spore * f_voc * (1.2 if active_mold_detected else 1.0))

        active_mold_risk = 0.0
        if active_mold_detected:
            active_mold_risk = 1.0
        elif mold_risk > 0.7 and spore_concentration > 1000:
            active_mold_risk = 0.8

        coverage_days: Optional[float] = None
        if avg_growth > 0.1:
            coverage_days = round(30.0 / (avg_growth * 10), 1) if avg_growth > 0 else None

        insect_risk = self._insect_risk_index(temp_c, rh_percent, spore_concentration)

        return MoldRiskResult(
            mold_risk_index=round(mold_risk, 4),
            mold_growth_rate=round(avg_growth, 5),
            germination_likelihood=round(avg_germination, 4),
            mycelium_coverage_days=coverage_days,
            spore_production_risk=round(min(1.0, avg_spore * f_spore), 4),
            active_mold_risk=round(active_mold_risk, 4),
            insect_risk_index=round(insect_risk, 4),
            mold_species=active_species[:3],
        )

    def _insect_risk_index(
        self,
        temp_c: float,
        rh_percent: float,
        spore_concentration: float,
    ) -> float:
        f_T = 0.0
        if 18 <= temp_c <= 35:
            if temp_c <= 28:
                f_T = (temp_c - 18) / 10.0
            else:
                f_T = 1.0 - (temp_c - 28) / 7.0
            f_T = max(0.0, min(1.0, f_T))

        RH = rh_percent / 100.0
        f_RH = 0.0
        if 0.50 <= RH <= 0.85:
            if RH <= 0.70:
                f_RH = (RH - 0.50) / 0.20
            else:
                f_RH = 1.0 - (RH - 0.70) / 0.15
            f_RH = max(0.0, min(1.0, f_RH))

        f_spore = min(1.0, spore_concentration / 800.0)
        return min(1.0, 0.55 * f_T * f_RH + 0.2 * f_spore + 0.1)


mold_growth_model = MoldGrowthModel()
