"""
古代防蠹药方知识图谱与推荐引擎
关联病害类型 -> 古籍医籍 -> 记载药材 -> 使用方法
"""
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from ..database import get_ch

logger = logging.getLogger(__name__)


@dataclass
class HerbRecipe:
    herb_id: str
    herb_cn_name: str
    source_book: str
    source_dynasty: str
    usage_method: str
    target_pests: List[str]
    efficacy: str
    toxicity_level: str
    compatibility: List[str]
    match_score: float = 0.0


DISEASE_HERB_MAPPING = {
    "ACIDOSIS": {
        "keywords": ["霉菌", "酸化"],
        "prioritize": ["HRB-006", "HRB-002", "HRB-005"],
        "avoid": [],
    },
    "MOLD": {
        "keywords": ["霉菌"],
        "prioritize": ["HRB-002", "HRB-005", "HRB-006", "HRB-008"],
        "avoid": [],
    },
    "ACTIVE_MOLD": {
        "keywords": ["霉菌", "蠹虫"],
        "prioritize": ["HRB-003", "HRB-002", "HRB-007"],
        "avoid": [],
    },
    "INSECT": {
        "keywords": ["蠹鱼", "甲虫", "衣蛾", "蠹虫"],
        "prioritize": ["HRB-001", "HRB-003", "HRB-004", "HRB-007"],
        "avoid": [],
    },
    "LIGHT": {
        "keywords": [],
        "prioritize": ["HRB-001", "HRB-005"],
        "avoid": [],
    },
}


class KnowledgeGraphService:

    def __init__(self):
        self.ch = get_ch()
        self._herb_cache: Optional[List[Dict]] = None

    def _load_herbs(self) -> List[Dict]:
        if self._herb_cache is None:
            try:
                self._herb_cache = self.ch.query("SELECT * FROM herb_knowledge_graph ORDER BY herb_id")
            except Exception as e:
                logger.error(f"Load herb graph failed: {e}")
                self._herb_cache = self._get_builtin_herbs()
        return self._herb_cache

    @staticmethod
    def _get_builtin_herbs() -> List[Dict]:
        return [
            {"herb_id": "HRB-001", "herb_cn_name": "芸草", "source_book": "梦溪笔谈",
             "source_dynasty": "宋", "usage_method": "阴干后夹于书页间，每册3-5株",
             "target_pests": ["蠹鱼", "衣鱼"],
             "efficacy": "香气驱虫，防蛀辟蠹，不伤纸墨",
             "toxicity_level": "LOW", "compatibility": ["麝香", "檀香"]},
            {"herb_id": "HRB-002", "herb_cn_name": "黄柏", "source_book": "本草纲目",
             "source_dynasty": "明", "usage_method": "煎汁浸染纸张，晾干后装订",
             "target_pests": ["蠹鱼", "甲虫", "霉菌"],
             "efficacy": "苦味驱虫，性寒防霉，可千年不蛀",
             "toxicity_level": "LOW", "compatibility": ["明矾", "五倍子"]},
            {"herb_id": "HRB-003", "herb_cn_name": "樟脑", "source_book": "本草纲目",
             "source_dynasty": "明", "usage_method": "研末撒于书柜四角，或制香包悬挂",
             "target_pests": ["蠹虫", "衣蛾", "鼠妇"],
             "efficacy": "升华驱虫，挥发性强，速杀成虫",
             "toxicity_level": "MEDIUM", "compatibility": ["薄荷", "荆芥"]},
            {"herb_id": "HRB-004", "herb_cn_name": "椒香", "source_book": "齐民要术",
             "source_dynasty": "北魏", "usage_method": "花椒研末，和泥糊书橱缝隙",
             "target_pests": ["白鱼", "尘螨"],
             "efficacy": "麻味杀虫，性热辟湿",
             "toxicity_level": "LOW", "compatibility": ["茱萸", "干姜"]},
            {"herb_id": "HRB-005", "herb_cn_name": "五倍子", "source_book": "本草经疏",
             "source_dynasty": "明", "usage_method": "煎汁涂纸，或研末入香囊",
             "target_pests": ["霉菌", "蠹鱼"],
             "efficacy": "固涩收敛，杀蛀防霉，兼固字迹",
             "toxicity_level": "LOW", "compatibility": ["黄柏", "明矾"]},
            {"herb_id": "HRB-006", "herb_cn_name": "明矾", "source_book": "天工开物",
             "source_dynasty": "明", "usage_method": "水溶后浸纸，为防染纸基础",
             "target_pests": ["霉菌", "酸化"],
             "efficacy": "固色防腐，抑酸护纸",
             "toxicity_level": "LOW", "compatibility": ["五倍子", "黄檗"]},
            {"herb_id": "HRB-007", "herb_cn_name": "麝香", "source_book": "名医别录",
             "source_dynasty": "魏晋", "usage_method": "少量研末制香囊，置于书匣",
             "target_pests": ["百虫"],
             "efficacy": "开窍辟秽，芳香驱虫，药力强劲",
             "toxicity_level": "HIGH", "compatibility": ["芸草", "沉香"]},
            {"herb_id": "HRB-008", "herb_cn_name": "艾叶", "source_book": "名医别录",
             "source_dynasty": "魏晋", "usage_method": "每年端午晒后夹书，或烟熏书库",
             "target_pests": ["蠹虫", "霉菌", "虫卵"],
             "efficacy": "温经辟秽，烟熏杀卵，取材便利",
             "toxicity_level": "LOW", "compatibility": ["菖蒲", "雄黄"]},
        ]

    def recommend_herbs(
        self,
        disease_types: List[str],
        mold_risk: float = 0.0,
        insect_risk: float = 0.0,
        ph_value: Optional[float] = None,
        top_k: int = 4,
        book_dynasty: str = "",
    ) -> Dict:
        herbs = self._load_herbs()
        all_scores: List[Tuple[float, Dict]] = []

        active_diseases = [d for d in disease_types if d in DISEASE_HERB_MAPPING]
        if not active_diseases:
            if insect_risk > 0.3:
                active_diseases.append("INSECT")
            if mold_risk > 0.3:
                active_diseases.append("MOLD")
            if ph_value is not None and ph_value < 6.0:
                active_diseases.append("ACIDOSIS")

        for herb in herbs:
            score = 0.0
            reasons = []
            herb_id = herb.get("herb_id", "")
            targets = set(herb.get("target_pests", []))

            for disease in active_diseases:
                meta = DISEASE_HERB_MAPPING.get(disease, {})
                if herb_id in meta.get("avoid", []):
                    score -= 0.5
                    continue
                if herb_id in meta.get("prioritize", []):
                    score += 0.6
                    reasons.append(f"针对{ALERT_TYPES_CN.get(disease, disease)}优先推荐")
                for kw in meta.get("keywords", []):
                    if kw in targets or kw in herb.get("efficacy", ""):
                        score += 0.3
                        reasons.append(f"对「{kw}」有效")

            if insect_risk > 0.5 and targets & {"蠹鱼", "蠹虫", "甲虫", "衣蛾", "百虫", "虫卵"}:
                score += 0.3 * insect_risk
                reasons.append(f"虫蛀风险匹配度 {int(insect_risk * 100)}%")
            if mold_risk > 0.5 and "霉菌" in targets:
                score += 0.3 * mold_risk
                reasons.append(f"霉菌风险匹配度 {int(mold_risk * 100)}%")
            if ph_value is not None and ph_value < 6.0 and ("酸化" in targets or "霉菌" in targets):
                score += 0.2
                reasons.append("适合低pH纸质")

            toxicity = herb.get("toxicity_level", "LOW")
            if toxicity == "HIGH":
                score -= 0.2
            if toxicity == "LOW":
                score += 0.1

            dynasty = herb.get("source_dynasty", "")
            if book_dynasty and dynasty in ("明", "清") and dynasty == book_dynasty:
                score += 0.05
                reasons.append(f"与藏书同朝({dynasty})应用经验")

            all_scores.append((score, herb, reasons))

        all_scores.sort(key=lambda x: x[0], reverse=True)
        top = all_scores[:top_k]

        recipes = []
        for score, herb, reasons in top:
            recipes.append({
                "herb": HerbRecipe(
                    herb_id=herb.get("herb_id", ""),
                    herb_cn_name=herb.get("herb_cn_name", ""),
                    source_book=herb.get("source_book", ""),
                    source_dynasty=herb.get("source_dynasty", ""),
                    usage_method=herb.get("usage_method", ""),
                    target_pests=list(herb.get("target_pests", [])),
                    efficacy=herb.get("efficacy", ""),
                    toxicity_level=herb.get("toxicity_level", "LOW"),
                    compatibility=list(herb.get("compatibility", [])),
                    match_score=round(max(0.0, min(1.0, score)), 3),
                ),
                "reasons": reasons,
            })

        best_recipe = recipes[0] if recipes else None
        compat_herbs = []
        if best_recipe and best_recipe["herb"].compatibility:
            compat_ids = []
            for h in recipes[1:]:
                if h["herb"].herb_cn_name in best_recipe["herb"].compatibility:
                    compat_herbs.append({
                        "herb_cn_name": h["herb"].herb_cn_name,
                        "usage": h["herb"].usage_method,
                    })
                    compat_ids.append(h["herb"].herb_id)

        return {
            "disease_types": active_diseases,
            "recommended_recipes": [
                {
                    "herb_id": r["herb"].herb_id,
                    "herb_cn_name": r["herb"].herb_cn_name,
                    "source": f"{r['herb'].source_dynasty}·{r['herb'].source_book}",
                    "usage_method": r["herb"].usage_method,
                    "target_pests": r["herb"].target_pests,
                    "efficacy": r["herb"].efficacy,
                    "toxicity": r["herb"].toxicity_level,
                    "match_score": r["herb"].match_score,
                    "reasons": r["reasons"],
                }
                for r in recipes
            ],
            "compatibility_suggestion": {
                "base_herb": best_recipe["herb"].herb_cn_name if best_recipe else "",
                "compatible_with": compat_herbs,
                "tip": (
                    f"以「{best_recipe['herb'].herb_cn_name}」为主，"
                    f"可配伍 {', '.join(h['herb_cn_name'] for h in compat_herbs)} "
                    f"以增强药效" if compat_herbs else "暂无推荐配伍"
                )
            } if best_recipe else {},
        }

    def get_herb_graph(self) -> List[Dict]:
        herbs = self._load_herbs()
        nodes = []
        links = []
        for h in herbs:
            nodes.append({"id": h["herb_id"], "name": h["herb_cn_name"],
                          "category": "herb", "source": f"{h['source_dynasty']}·{h['source_book']}"})
            for pest in h.get("target_pests", []):
                pest_id = f"PEST-{pest}"
                if not any(n["id"] == pest_id for n in nodes):
                    nodes.append({"id": pest_id, "name": pest, "category": "pest"})
                links.append({"source": h["herb_id"], "target": pest_id, "relation": "防治"})
            for comp in h.get("compatibility", []):
                cid = f"HERB-COMP-{comp}"
                if not any(n["id"] == cid for n in nodes):
                    nodes.append({"id": cid, "name": comp, "category": "herb"})
                links.append({"source": h["herb_id"], "target": cid, "relation": "配伍"})
        return {"nodes": nodes, "links": links}

    def get_all_herbs(self) -> List[Dict]:
        herbs = self._load_herbs()
        return [
            {
                "herb_id": h["herb_id"],
                "herb_cn_name": h["herb_cn_name"],
                "source_book": h["source_book"],
                "source_dynasty": h["source_dynasty"],
                "usage_method": h["usage_method"],
                "target_pests": list(h.get("target_pests", [])),
                "efficacy": h["efficacy"],
                "toxicity_level": h["toxicity_level"],
                "compatibility": list(h.get("compatibility", [])),
            }
            for h in herbs
        ]


ALERT_TYPES_CN = {
    "ACIDOSIS": "纸张酸化",
    "MOLD": "霉菌超标",
    "LIGHT": "光照过强",
    "INSECT": "虫蛀风险",
    "ACTIVE_MOLD": "活性霉菌",
}

knowledge_graph = KnowledgeGraphService()
