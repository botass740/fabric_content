import json
import logging
from app.generators.openrouter_client import OpenRouterClient
from app.generators.utils import load_prompt


def generate_article_plan(
    settings,
    *,
    topic: str,
    title: str,
    hero: str,
    emotion: str,
    format: str,
) -> str:
    """
    Генерирует структурированный план статьи.
    Возвращает читаемую текстовую версию плана для передачи в article_prompt.
    """
    logger = logging.getLogger(__name__)

    prompt_text = load_prompt(settings, "article_plan_prompt.txt")
    user_prompt = prompt_text.format(
        topic=topic,
        title=title,
        hero=hero,
        emotion=emotion,
        format=format,
    )

    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_s=settings.openrouter_timeout_s,
        logger=logger,
    )

    system = "Ты редактор Яндекс Дзена. Возвращай только JSON без пояснений и markdown."

    response = client.chat(
        system=system,
        user=user_prompt,
        temperature=0.75,
        max_tokens=1800,
    )

    try:
        plan_json = json.loads(response)
    except Exception:
        import re
        match = re.search(r'\{.+\}', response, re.DOTALL)
        if match:
            try:
                plan_json = json.loads(match.group(0))
            except Exception as e:
                logger.error(f"Failed to parse plan JSON: {response[:500]}")
                raise ValueError(f"Cannot parse article plan: {e}")
        else:
            logger.error(f"No JSON found in response: {response[:500]}")
            raise ValueError("No JSON in article plan response")

    plan_text = f"""
Главный инсайт:
{plan_json.get('core_insight', '')}

Дополнительные инсайты:
{chr(10).join('- ' + i for i in plan_json.get('supporting_insights', []))}

Эмоциональная арка:
{' → '.join(plan_json.get('emotion_arc', []))}

Структура:
- Хук: {plan_json.get('hook_goal', '')}
- Бытовая сцена: {plan_json.get('scene_goal', '')}
- Твист: {plan_json.get('twist_goal', '')}
- Развитие идеи:
{chr(10).join('  * ' + g for g in plan_json.get('development_goals', []))}
- Финал: {plan_json.get('ending_goal', '')}

Бытовые детали:
{chr(10).join('- ' + d for d in plan_json.get('details', []))}

Финальная мысль/образ:
{plan_json.get('final_image', '')}
""".strip()

    logger.info(f"Generated article plan for: {title[:50]}")
    return plan_text
