"""
Библиотека шаблонов промтов для обложек.
Каждый шаблон описывает визуальный сценарий для определённого типа статьи.
"""

IMAGE_TEMPLATES = {
    "financial_mistake": {
        "description": "Финансовая ошибка, сожаление о потраченных деньгах",
        "prompt_template": """Photorealistic cinematic shot: {subject} in {location}, {emotion} expression, dramatic natural lighting.
Main focus: {main_object}.
Color palette: dark tones with {accent_color} accents.
Atmosphere: {atmosphere}.
Shot on professional camera, high detail, no text, no watermarks, 16:9 aspect ratio.""",
        "defaults": {
            "subject": "a middle-aged person",
            "location": "home kitchen or living room",
            "emotion": "regretful or stressed",
            "main_object": "bills, receipts, or empty wallet on table",
            "accent_color": "red or orange",
            "atmosphere": "tension, realization of mistake"
        }
    },

    "money_loss": {
        "description": "Потеря денег, финансовый удар",
        "prompt_template": """Cinematic photorealistic image: {subject} {action}, {emotion}.
Main element: {main_object}.
Lighting: {lighting}.
Color scheme: {colors}.
Mood: {mood}.
Professional photography, extreme detail, no text overlay, 16:9.""",
        "defaults": {
            "subject": "person",
            "action": "looking at phone or documents with shock",
            "emotion": "anxiety, disbelief",
            "main_object": "smartphone showing bank notification, or empty wallet",
            "lighting": "dramatic side lighting from window",
            "colors": "muted grays with red warning accents",
            "mood": "financial anxiety, sudden realization"
        }
    },

    "smart_saving": {
        "description": "Успешная экономия, правильное финансовое решение",
        "prompt_template": """Photorealistic shot: {subject} in {location}, {emotion}.
Central object: {main_object}.
Lighting: {lighting}.
Color palette: {colors}.
Atmosphere: {atmosphere}.
High-end photography, natural look, no graphics, 16:9 format.""",
        "defaults": {
            "subject": "person smiling slightly",
            "location": "clean modern interior",
            "emotion": "satisfied, calm confidence",
            "main_object": "organized documents, savings jar, or neat wallet",
            "lighting": "warm natural light",
            "colors": "warm tones with gold/yellow accents",
            "atmosphere": "success, control over finances"
        }
    },

    "impulse_purchase": {
        "description": "Импульсивная покупка, соблазн скидок",
        "prompt_template": """Cinematic realism: {subject} {action}, expression shows {emotion}.
Focus on: {main_object}.
Setting: {location}.
Lighting: {lighting}.
Colors: {colors}.
Emotional tone: {mood}.
Professional camera work, photojournalistic style, 16:9.""",
        "defaults": {
            "subject": "person with shopping bags",
            "action": "standing in store or at home surrounded by purchases",
            "emotion": "mix of excitement and doubt",
            "main_object": "shopping bags, price tags, sale signs in background",
            "location": "retail store or apartment entrance",
            "lighting": "bright commercial or home lighting",
            "colors": "bright reds and yellows (sale colors) with neutral background",
            "mood": "temptation, immediate regret"
        }
    },

    "work_money": {
        "description": "Работа, заработок, карьера",
        "prompt_template": """Photorealistic professional shot: {subject} in {location}, {emotion}.
Main element: {main_object}.
Lighting: {lighting}.
Color scheme: {colors}.
Mood: {mood}.
Commercial photography quality, sharp focus, 16:9 aspect ratio.""",
        "defaults": {
            "subject": "professional person at work",
            "location": "office or workspace",
            "emotion": "focused, determined",
            "main_object": "laptop, documents, or hands typing",
            "lighting": "office lighting with natural window light",
            "colors": "neutral professional tones with blue or green accents",
            "mood": "productivity, earning"
        }
    },

    "fraud_warning": {
        "description": "Мошенничество, финансовая опасность",
        "prompt_template": """Dramatic photorealistic image: {subject} {action}, {emotion} visible.
Key object: {main_object}.
Environment: {location}.
Lighting: {lighting}.
Color palette: {colors}.
Atmosphere: {atmosphere}.
Cinematic photography, tension, 16:9 format.""",
        "defaults": {
            "subject": "person",
            "action": "looking suspiciously at phone or card",
            "emotion": "suspicion, concern",
            "main_object": "phone with suspicious message, or credit card",
            "location": "dim indoor setting",
            "lighting": "dramatic contrast, phone screen as light source",
            "colors": "dark with red warning tones",
            "atmosphere": "danger, caution"
        }
    }
}


def get_template(category: str) -> dict:
    """Возвращает шаблон по категории или дефолтный"""
    return IMAGE_TEMPLATES.get(category, IMAGE_TEMPLATES["financial_mistake"])


def get_all_categories() -> list[str]:
    """Список всех доступных категорий"""
    return list(IMAGE_TEMPLATES.keys())