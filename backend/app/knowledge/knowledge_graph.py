from typing import Dict, List, Optional


DISEASE_HERB_MAP = {
    "acidification": {
        "name": "纸张酸化",
        "description": "纸张因环境因素导致pH值下降，引起纸张脆化变黄",
        "herbs": [
            {
                "name": "黄柏",
                "pinyin": "huáng bǎi",
                "latin": "Phellodendron chinense",
                "properties": "味苦，性寒。清热燥湿，泻火解毒。",
                "usage": "黄柏煎汁染纸，可使纸呈黄色，经久不褪，兼有防蛀、耐水之效",
                "references": ["《天工开物》", "《纸墨笺》", "《齐民要术》"],
                "efficacy": 8.5
            },
            {
                "name": "石灰",
                "pinyin": "shí huī",
                "latin": "Calx",
                "properties": "味辛，性温。燥湿，杀虫，止血，定痛。",
                "usage": "石灰水浸泡纸张，可中和纸张酸性，提高pH值",
                "references": ["《本草纲目》", "《天工开物》"],
                "efficacy": 7.0
            },
            {
                "name": "碳酸钙",
                "pinyin": "tàn suān gài",
                "latin": "Calcium carbonate",
                "properties": "味甘，性温。温中，收敛。",
                "usage": "碳酸钙溶液喷洒纸面，形成碱性保护层，延缓酸化",
                "references": ["《造纸技艺》"],
                "efficacy": 7.5
            }
        ],
        "prescriptions": [
            {
                "name": "黄柏染纸法",
                "method": "取黄柏一斤，锉碎，以水五升煮取二升，去滓。浸纸令透，取出阴干。",
                "efficacy": "染后纸色微黄，可防蛀、防酸、耐久藏",
                "source": "《齐民要术·杂说》"
            },
            {
                "name": "石灰水脱酸法",
                "method": "生石灰二两，水十升，化开澄清。取清液浸纸片时，取出晾干。",
                "efficacy": "可提高纸张pH值1-2个单位，延缓酸化进程",
                "source": "《天工开物·杀青》"
            }
        ],
        "prevention_tips": [
            "控制库房温度在18-22℃",
            "相对湿度保持在45-55%",
            "使用碱性纸张装裱修复",
            "定期检测纸张pH值"
        ]
    },
    "mold": {
        "name": "霉变",
        "description": "霉菌在纸张表面生长，导致纸张污损、强度下降",
        "herbs": [
            {
                "name": "芸草",
                "pinyin": "yún cǎo",
                "latin": "Ruta graveolens",
                "properties": "味辛、苦，性寒。清热解毒，散瘀止血。",
                "usage": "晒干置于书间，其香气可驱虫防霉，古称'书香'即源于此",
                "references": ["《梦溪笔谈》", "《本草纲目》", "《香乘》"],
                "efficacy": 9.0
            },
            {
                "name": "樟脑",
                "pinyin": "zhāng nǎo",
                "latin": "Camphora",
                "properties": "味辛，性热。通关窍，利滞气，杀虫止痒。",
                "usage": "樟脑块置于书橱四角，挥发之气可防霉驱虫",
                "references": ["《本草纲目》", "《外科大成》"],
                "efficacy": 8.0
            },
            {
                "name": "苍术",
                "pinyin": "cāng zhú",
                "latin": "Atractylodes lancea",
                "properties": "味辛、苦，性温。燥湿健脾，祛风散寒。",
                "usage": "苍术焚烧熏库，其烟气可消毒防霉，古称'熏库法'",
                "references": ["《本草纲目》", "《遵生八笺》"],
                "efficacy": 7.5
            },
            {
                "name": "艾叶",
                "pinyin": "ài yè",
                "latin": "Artemisia argyi",
                "properties": "味辛、苦，性温。散寒止痛，温经止血。",
                "usage": "干艾叶夹于书页间，或艾烟熏库，可防霉防虫",
                "references": ["《本草纲目》", "《古今图书集成》"],
                "efficacy": 7.0
            }
        ],
        "prescriptions": [
            {
                "name": "芸香避蠹法",
                "method": "采芸草，阴干，每册置两三本于书根处。其香清远，可辟蠹鱼，且无油垢之患。",
                "efficacy": "芸香辟蠹，为古人藏书首法，兼可香书",
                "source": "《梦溪笔谈·辩证一》"
            },
            {
                "name": "苍术熏库法",
                "method": "苍术半斤，锉碎，于密室中焚烧，闭户熏之。每月一次，可避霉蛀。",
                "efficacy": "烟气消毒，防霉效果显著，兼能驱湿",
                "source": "《遵生八笺·起居安乐笺》"
            }
        ],
        "prevention_tips": [
            "保持库房干燥，相对湿度不超过60%",
            "定期通风换气",
            "使用芸草、樟脑等天然防霉剂",
            "发现霉变及时隔离处理"
        ]
    },
    "insect": {
        "name": "虫蛀",
        "description": "蛀虫啃食纸张，造成孔洞和缺损",
        "herbs": [
            {
                "name": "芸草",
                "pinyin": "yún cǎo",
                "latin": "Ruta graveolens",
                "properties": "味辛、苦，性寒。杀虫解毒。",
                "usage": "置于书间，其香气可驱杀蠹鱼、书虱等害虫",
                "references": ["《齐民要术》", "《梦溪笔谈》", "《本草纲目》"],
                "efficacy": 9.5
            },
            {
                "name": "雄黄",
                "pinyin": "xióng huáng",
                "latin": "Realgar",
                "properties": "味辛，性温，有毒。解毒杀虫，燥湿祛痰。",
                "usage": "研末撒于书橱或书页间，可杀蛀虫",
                "references": ["《本草纲目》", "《神农本草经》"],
                "efficacy": 8.5
            },
            {
                "name": "雌黄",
                "pinyin": "cí huáng",
                "latin": "Orpiment",
                "properties": "味辛，性平，有毒。燥湿，杀虫，解毒。",
                "usage": "雌黄粉涂纸，既可改字，又能防蛀",
                "references": ["《梦溪笔谈》", "《本草纲目》"],
                "efficacy": 8.0
            },
            {
                "name": "苦楝",
                "pinyin": "kǔ liàn",
                "latin": "Melia azedarach",
                "properties": "味苦，性寒，有毒。杀虫，疗癣。",
                "usage": "苦楝皮造纸或染纸，纸味苦，蠹虫不食",
                "references": ["《齐民要术》", "《本草纲目》"],
                "efficacy": 8.0
            }
        ],
        "prescriptions": [
            {
                "name": "芸草藏书法",
                "method": "七月七日收芸草，阴干，置书帙中，即无蠹鱼。或蒸过曝干，尤佳。",
                "efficacy": "芸香辟蠹，为藏书第一妙法，兼可令书有香气",
                "source": "《齐民要术·杂说》"
            },
            {
                "name": "雄黄熏书法",
                "method": "雄黄、雌黄各等分，研细末，于密闭柜中熏书。",
                "efficacy": "杀虫效果显著，可杀蛀虫、衣鱼等",
                "source": "《藏书纪要·收藏》"
            },
            {
                "name": "苦楝纸法",
                "method": "以苦楝皮煮水，和入纸浆抄纸。或用纸浸染苦楝汁。",
                "efficacy": "纸味苦，蠹虫不食，防虫效果持久",
                "source": "《天工开物·杀青》"
            }
        ],
        "prevention_tips": [
            "新书入藏前先进行杀虫处理",
            "定期检查书况，发现虫蛀及时隔离",
            "使用芸草、樟脑等防蠹药物",
            "保持库房清洁，减少虫源"
        ]
    },
    "light_damage": {
        "name": "光照老化",
        "description": "光照导致纸张纤维素降解、褪色",
        "herbs": [
            {
                "name": "槐花",
                "pinyin": "huái huā",
                "latin": "Sophora japonica",
                "properties": "味苦，性微寒。凉血止血，清肝泻火。",
                "usage": "槐花汁染纸，黄色素可吸收部分紫外线，减轻光损伤",
                "references": ["《天工开物》", "《本草纲目》"],
                "efficacy": 6.5
            },
            {
                "name": "五倍子",
                "pinyin": "wǔ bèi zǐ",
                "latin": "Galla chinensis",
                "properties": "味酸、涩，性寒。敛肺降火，涩肠止泻。",
                "usage": "五倍子液处理纸张，可固色并形成保护膜",
                "references": ["《本草纲目》", "《装潢志》"],
                "efficacy": 7.0
            },
            {
                "name": "皂角",
                "pinyin": "zào jiǎo",
                "latin": "Gleditsia sinensis",
                "properties": "味辛，性温，有小毒。开窍，祛痰，杀虫。",
                "usage": "皂角水净纸，可去污并在纸面形成保护膜",
                "references": ["《多能鄙事》", "《本草纲目》"],
                "efficacy": 6.0
            }
        ],
        "prescriptions": [
            {
                "name": "槐花染纸防光法",
                "method": "槐花煎浓汁，染纸令透，阴干。纸色金黄，可防光褪色。",
                "efficacy": "黄色素吸收紫外线，减轻光老化",
                "source": "《天工开物·彰施》"
            },
            {
                "name": "五倍子固色法",
                "method": "五倍子煮水，滤过，以纸浸之，取出晾干。可使纸面光滑，颜色持久。",
                "efficacy": "形成保护膜，延缓光老化",
                "source": "《装潢志·治糊》"
            }
        ],
        "prevention_tips": [
            "库房避免阳光直射",
            "使用防紫外线玻璃或窗帘",
            "照明使用冷光源，照度不超过50 lux",
            "善本书籍尽量减少展示时间"
        ]
    },
    "humidity_damage": {
        "name": "潮湿损伤",
        "description": "高湿导致纸张变形、粘连、滋生霉菌",
        "herbs": [
            {
                "name": "石灰",
                "pinyin": "shí huī",
                "latin": "Calx",
                "properties": "味辛，性温。燥湿，杀虫。",
                "usage": "生石灰块置于书橱底部，吸收潮气",
                "references": ["《便民图纂》", "《本草纲目》"],
                "efficacy": 8.0
            },
            {
                "name": "木炭",
                "pinyin": "mù tàn",
                "latin": "Carbon",
                "properties": "味甘，性温。吸潮，除臭。",
                "usage": "木炭用纱布包裹，置于书橱各层，吸潮除臭",
                "references": ["《多能鄙事》", "《便民图纂》"],
                "efficacy": 7.5
            },
            {
                "name": "皂角",
                "pinyin": "zào jiǎo",
                "latin": "Gleditsia sinensis",
                "properties": "味辛，性温。开窍，祛痰，除湿。",
                "usage": "皂角水清洗受潮书页，可防粘连",
                "references": ["《多能鄙事》"],
                "efficacy": 6.0
            }
        ],
        "prescriptions": [
            {
                "name": "石灰除湿法",
                "method": "生石灰块盛于木箱中，置书橱底层或四隅。待潮解后更换。",
                "efficacy": "吸潮力强，可有效降低书橱内湿度",
                "source": "《便民图纂·杂类》"
            },
            {
                "name": "木炭吸潮法",
                "method": "木炭烧红，放凉，以布包之，置书间。每月一换。",
                "efficacy": "吸潮兼除臭，温和不损伤书籍",
                "source": "《多能鄙事·文房》"
            }
        ],
        "prevention_tips": [
            "雨季紧闭门窗，防止潮气侵入",
            "使用除湿机控制库房湿度",
            "书橱放置吸潮剂（石灰、木炭等）",
            "书籍不宜靠墙放置，保持通风"
        ]
    }
}


HERB_DETAIL_MAP = {}
for disease_type, disease_info in DISEASE_HERB_MAP.items():
    for herb in disease_info["herbs"]:
        if herb["name"] not in HERB_DETAIL_MAP:
            HERB_DETAIL_MAP[herb["name"]] = herb


class KnowledgeGraphService:
    """
    古籍病害与药方知识图谱服务
    根据病害类型推荐相关医籍中记载的古代防蠹药方
    """

    def get_disease_info(self, disease_type: str) -> Optional[Dict]:
        """获取病害详细信息"""
        return DISEASE_HERB_MAP.get(disease_type)

    def get_recommendations_by_disease(self, disease_type: str) -> Dict:
        """
        根据病害类型推荐防治方法和药方
        """
        disease_info = DISEASE_HERB_MAP.get(disease_type)
        if not disease_info:
            return {"error": f"未找到病害类型: {disease_type}"}

        return {
            "disease_type": disease_type,
            "disease_name": disease_info["name"],
            "description": disease_info["description"],
            "recommended_herbs": disease_info["herbs"],
            "recommended_prescriptions": disease_info["prescriptions"],
            "prevention_tips": disease_info["prevention_tips"],
            "related_books": self._get_related_books(disease_type)
        }

    def get_recommendations_by_shelf(self, shelf_id: str,
                                      risk_types: List[str]) -> List[Dict]:
        """
        根据书架位置和风险类型推荐防治方案
        """
        recommendations = []
        for risk_type in risk_types:
            rec = self.get_recommendations_by_disease(risk_type)
            if "error" not in rec:
                recommendations.append(rec)
        return recommendations

    def search_herb(self, herb_name: str) -> Optional[Dict]:
        """搜索药材信息"""
        return HERB_DETAIL_MAP.get(herb_name)

    def get_all_disease_types(self) -> List[Dict]:
        """获取所有病害类型"""
        return [
            {"type": k, "name": v["name"], "description": v["description"]}
            for k, v in DISEASE_HERB_MAP.items()
        ]

    def _get_related_books(self, disease_type: str) -> List[str]:
        """获取与病害相关的古籍参考文献"""
        disease_info = DISEASE_HERB_MAP.get(disease_type)
        if not disease_info:
            return []

        refs = set()
        for herb in disease_info["herbs"]:
            refs.update(herb.get("references", []))
        for prescription in disease_info["prescriptions"]:
            if "source" in prescription:
                refs.add(prescription["source"].split("·")[0] if "·" in prescription["source"] else prescription["source"])

        return list(refs)

    def get_comprehensive_recommendation(self, risk_assessment: Dict) -> Dict:
        """
        根据综合风险评估生成完整的防治建议
        """
        primary_risks = risk_assessment.get("primary_risks", [])
        recommendations = []

        for risk in primary_risks:
            rec = self.get_recommendations_by_disease(risk)
            if "error" not in rec:
                recommendations.append(rec)

        all_herbs = []
        seen_herbs = set()
        for rec in recommendations:
            for herb in rec.get("recommended_herbs", []):
                if herb["name"] not in seen_herbs:
                    all_herbs.append(herb)
                    seen_herbs.add(herb["name"])

        all_prescriptions = []
        for rec in recommendations:
            all_prescriptions.extend(rec.get("recommended_prescriptions", []))

        all_tips = []
        for rec in recommendations:
            all_tips.extend(rec.get("prevention_tips", []))

        priority = "normal"
        if risk_assessment.get("overall_risk_level") == "critical":
            priority = "urgent"
        elif risk_assessment.get("overall_risk_level") == "warning":
            priority = "high"

        return {
            "overall_risk_level": risk_assessment.get("overall_risk_level"),
            "overall_risk_score": risk_assessment.get("overall_risk_score"),
            "priority": priority,
            "target_risks": primary_risks,
            "recommended_herbs": all_herbs,
            "recommended_prescriptions": all_prescriptions,
            "prevention_tips": all_tips,
            "action_suggestion": self._get_action_suggestion(priority)
        }

    def _get_action_suggestion(self, priority: str) -> str:
        suggestions = {
            "urgent": "建议立即采取防治措施，将该区域书籍转移至安全环境，并请专业人员进行处理。",
            "high": "建议在一周内采取防治措施，加强监控频率，密切关注病害发展情况。",
            "normal": "建议按日常维护计划进行处理，保持正常监控频率即可。"
        }
        return suggestions.get(priority, "请根据实际情况采取适当措施。")
