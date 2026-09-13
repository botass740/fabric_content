# -*- coding: utf-8 -*-
"""Одноразовый анализ research.db: 5 JSON-файлов + финальный отчёт.
LLM не используется, только pandas/numpy/scipy + sqlite3 + re.

Запуск:
  python tools/research_analysis.py
"""
import json
import os
import re
import sqlite3
from collections import Counter
from statistics import median, mean

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

# --- paths ---
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "data", "research.db")
OUR_TXT = os.path.join(ROOT, "data", "analysis_source", "our_articles.txt")
OUT_DIR = os.path.join(ROOT, "data", "research", "analysis")
os.makedirs(OUT_DIR, exist_ok=True)

# стоп-слова русские (минимальный набор для частотного анализа заголовков)
STOP_WORDS = {
    "и", "в", "на", "по", "с", "со", "для", "не", "что", "как", "это",
    "к", "из", "за", "от", "до", "но", "он", "она", "мы", "вы", "они",
    "у", "о", "же", "бы", "ли", "то", "все", "уже", "да", "нет", "его",
    "её", "их", "вас", "нас", "мне", "тебе", "ему", "ей", "им", "этот",
    "эта", "эти", "тот", "та", "те", "так", "там", "тут", "ещё", "еще",
    "или", "ни", "при", "без", "через", "над", "под", "про", "между",
    "чтобы", "если", "когда", "пока", "лишь", "даже", "очень", "более",
    "менее", "где", "куда", "откуда", "почему", "зачем", "сколько",
    "раз", "два", "три", "четыре", "пять", "много", "мало",
    "будет", "был", "была", "были", "есть", "стал", "стала", "стали",
    "может", "могут", "надо", "нужно", "стоит", "хочу", "хочет",
    "почём", "моя", "твоя", "наша", "ваша", "моих", "твоих",
    "этого", "этой", "этих", "того", "той", "тех",
    "а", "б", "вот", "только", "просто", "теперь", "сейчас",
    "который", "которая", "которые", "которых", "которой", "которого",
    "свой", "своя", "свои", "своих",
}

# "имена героев" — простые русские имена в именительном (без отчеств)
HERO_FIRST_NAMES = {
    "анна", "мария", "марья", "ольга", "елена", "наталья", "татьяна",
    "ирина", "екатерина", "светлана", "юлия", "марина", "оксана",
    "валентина", "галина", "любовь", "надежда", "зоя", "тамара",
    "раиса", "василий", "василь", "иван", "петр", "пётр", "александр",
    "дмитрий", "сергей", "андрей", "михаил", "алексей", "максим",
    "артем", "артём", "илья", "илья", "никита", "денис", "евгений",
    "роман", "егор", "арсений", "владимир", "борис", "геннадий",
    "валерий", "виктор", "павел", "константин", "юрий", "михаил",
    "татьяна", "маргарита", "вероника", "алина", "диана", "кристина",
    "полина", "виктория", "анастасия", "дарья", "даша", "елена",
    "людмила", "зоя", "инна",
}


# ================================================================ load
def load_df():
    conn = sqlite3.connect(DB_PATH)
    # articles + channels
    df = pd.read_sql_query(
        """
        SELECT a.id, a.dzen_id, a.channel_id, a.url, a.title, a.text,
               a.text_length, a.word_count, a.published_at, a.collected_at,
               a.views, a.likes, a.comments, a.shares, a.time_to_read,
               a.paragraphs_count, a.headers_count,
               c.slug AS channel_slug, c.title AS channel_title
        FROM articles a
        LEFT JOIN channels c ON c.id = a.channel_id
        WHERE a.url IS NOT NULL
        """,
        conn,
    )
    conn.close()
    return df


# ================================================================ helpers
def has_digits(s):
    if not isinstance(s, str):
        return False
    return bool(re.search(r"\d", s))


def has_question(s):
    if not isinstance(s, str):
        return False
    return "?" in s


def has_rub(s):
    if not isinstance(s, str):
        return False
    return bool(re.search(r"₽|\bруб\b|\bрублей\b|\bтыс\.?\s*руб\b|\bмлн\s*руб\b", s, re.IGNORECASE))


def has_hero(s):
    if not isinstance(s, str):
        return False
    tokens = re.findall(r"[А-Яа-яёЁ]+", s.lower())
    return any(t in HERO_FIRST_NAMES for t in tokens)


def tokenize_title(s):
    if not isinstance(s, str):
        return []
    tokens = re.findall(r"[А-Яа-яёЁ]{2,}", s.lower())
    return [t for t in tokens if t not in STOP_WORDS]


def bigrams(tokens):
    return list(zip(tokens, tokens[1:]))


def median_int(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) == 0:
        return None
    return int(s.median())


# ================================================================ ШАГ 1
def step1_channels(df):
    grp = df.groupby("channel_id")
    rows = []
    for cid, g in grp:
        slug = g["channel_slug"].iloc[0] if "channel_slug" in g.columns else None
        title = g["channel_title"].iloc[0] if "channel_title" in g.columns else None
        n = len(g)
        med_v = median_int(g["views"])
        med_l = median_int(g["likes"])
        med_c = median_int(g["comments"])
        med_ttr = median_int(g["time_to_read"])
        if g["views"].notna().any():
            best = g.loc[g["views"].idxmax()]
            best_title = best["title"]
            best_views = int(best["views"])
        else:
            best_title, best_views = None, None
        avg_len = int(g["text_length"].mean()) if g["text_length"].notna().any() else None
        avg_ttr = int(g["time_to_read"].mean()) if g["time_to_read"].notna().any() else None
        rows.append({
            "channel_id": int(cid),
            "slug": slug,
            "title": title,
            "articles": n,
            "median_views": med_v,
            "median_likes": med_l,
            "median_comments": med_c,
            "best_title": best_title,
            "best_views": best_views,
            "avg_text_length": avg_len,
            "avg_time_to_read": avg_ttr,
        })
    rows.sort(key=lambda r: (r["median_views"] or 0), reverse=True)
    out = {"channels": rows, "n_channels": len(rows)}
    with open(os.path.join(OUT_DIR, "channels_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out


# ================================================================ ШАГ 2
def title_metrics(s):
    if not isinstance(s, str) or not s:
        return None
    return {
        "has_digit": has_digits(s),
        "has_question": has_question(s),
        "has_hero": has_hero(s),
        "has_rub": has_rub(s),
        "word_count": len(re.findall(r"\S+", s)),
        "char_count": len(s),
        "tokens": tokenize_title(s),
    }


def step2_titles(df):
    df = df.copy()
    df["title_m"] = df["title"].apply(title_metrics)
    df["tk_has_digit"] = df["title_m"].apply(lambda m: m["has_digit"] if m else False)
    df["tk_has_question"] = df["title_m"].apply(lambda m: m["has_question"] if m else False)
    df["tk_has_hero"] = df["title_m"].apply(lambda m: m["has_hero"] if m else False)
    df["tk_has_rub"] = df["title_m"].apply(lambda m: m["has_rub"] if m else False)
    df["tk_words"] = df["title_m"].apply(lambda m: m["word_count"] if m else 0)
    df["tk_chars"] = df["title_m"].apply(lambda m: m["char_count"] if m else 0)

    n = len(df)

    def pct(s):
        return round(100.0 * s.sum() / n, 1) if n else 0

    # топ-30 слов
    counter = Counter()
    for toks in df["title_m"].apply(lambda m: m["tokens"] if m else []):
        counter.update(toks)
    top30 = counter.most_common(30)
    # биграммы
    bg_counter = Counter()
    for toks in df["title_m"].apply(lambda m: m["tokens"] if m else []):
        bg_counter.update(bigrams(toks))
    top10_bg = [{"w1": w1, "w2": w2, "count": c} for (w1, w2), c in bg_counter.most_common(10)]

    all_avg = {
        "n": n,
        "avg_words": round(df["tk_words"].mean(), 1),
        "median_words": int(df["tk_words"].median()),
        "avg_chars": round(df["tk_chars"].mean(), 1),
        "median_chars": int(df["tk_chars"].median()),
        "pct_with_digit": pct(df["tk_has_digit"]),
        "pct_with_question": pct(df["tk_has_question"]),
        "pct_with_hero": pct(df["tk_has_hero"]),
        "pct_with_rub": pct(df["tk_has_rub"]),
    }

    # топ-20% по views (с views not null)
    df_v = df[df["views"].notna()].copy()
    if len(df_v):
        thr = df_v["views"].quantile(0.80)
        top = df_v[df_v["views"] >= thr]
        n_top = len(top)
        def pct_top(s):
            return round(100.0 * s.sum() / n_top, 1) if n_top else 0
        top_metrics = {
            "n": n_top,
            "threshold_views": int(thr),
            "avg_words": round(top["tk_words"].mean(), 1),
            "median_words": int(top["tk_words"].median()),
            "avg_chars": round(top["tk_chars"].mean(), 1),
            "median_chars": int(top["tk_chars"].median()),
            "pct_with_digit": pct_top(top["tk_has_digit"]),
            "pct_with_question": pct_top(top["tk_has_question"]),
            "pct_with_hero": pct_top(top["tk_has_hero"]),
            "pct_with_rub": pct_top(top["tk_has_rub"]),
        }
        # топ-слова в топ-20%
        top_counter = Counter()
        for toks in top["title_m"].apply(lambda m: m["tokens"] if m else []):
            top_counter.update(toks)
        top_top20 = top_counter.most_common(30)
        # diff: слова, у которых freq в топ-20% сильно выше чем в среднем
        diffs = []
        for w, c_top in top_counter.items():
            base = counter.get(w, 0)
            # нормируем на n
            freq_top = c_top / max(n_top, 1)
            freq_all = base / max(n, 1)
            ratio = freq_top / freq_all if freq_all > 0 else 0
            diffs.append({"word": w, "top_pct": round(freq_top * 100, 2),
                          "all_pct": round(freq_all * 100, 2), "ratio": round(ratio, 2)})
        diffs.sort(key=lambda x: x["ratio"], reverse=True)
        # отфильтруем слишком редкие (<2 в топе)
        diffs_sig = [d for d in diffs if d["top_pct"] >= 0.5][:15]
    else:
        top_metrics = {"n": 0}
        top_top20 = []
        diffs_sig = []

    out = {
        "all": all_avg,
        "top20pct_by_views": top_metrics,
        "top_words_all": top30,
        "top_words_top20pct": top_top20 if "top_top20" in dir() else [],
        "top_bigrams_all": top10_bg,
        "words_more_in_top": diffs_sig,
    }
    with open(os.path.join(OUT_DIR, "titles_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out, df


# ================================================================ ШАГ 3
def text_metrics(text):
    if not isinstance(text, str) or not text:
        return None
    return {
        "has_dialog": "«" in text and "»" in text,
        "has_rub": has_rub(text),
        "ends_with_question": text.rstrip().endswith("?"),
        "paragraphs": text.count("\n\n") + 1 if "\n" in text else 1,
    }


def step3_texts(df):
    df = df.copy()
    df["text_m"] = df["text"].apply(text_metrics)
    df["tx_has_dialog"] = df["text_m"].apply(lambda m: m["has_dialog"] if m else False)
    df["tx_has_rub"] = df["text_m"].apply(lambda m: m["has_rub"] if m else False)
    df["tx_ends_q"] = df["text_m"].apply(lambda m: m["ends_with_question"] if m else False)
    df["tx_paras"] = df["text_m"].apply(lambda m: m["paragraphs"] if m else 0)

    n = len(df)
    lens = pd.to_numeric(df["text_length"], errors="coerce").dropna()
    paras = pd.to_numeric(df["paragraphs_count"], errors="coerce").dropna()

    def pct(s):
        return round(100.0 * s.sum() / n, 1) if n else 0

    all_metrics = {
        "n": n,
        "avg_text_length": int(lens.mean()) if len(lens) else None,
        "median_text_length": int(lens.median()) if len(lens) else None,
        "q25_text_length": int(lens.quantile(0.25)) if len(lens) else None,
        "q75_text_length": int(lens.quantile(0.75)) if len(lens) else None,
        "avg_paragraphs": round(paras.mean(), 1) if len(paras) else None,
        "median_paragraphs": int(paras.median()) if len(paras) else None,
        "pct_with_dialog": pct(df["tx_has_dialog"]),
        "pct_with_rub": pct(df["tx_has_rub"]),
        "pct_ends_with_question": pct(df["tx_ends_q"]),
    }

    # топ-20% по views
    df_v = df[df["views"].notna()].copy()
    if len(df_v):
        thr = df_v["views"].quantile(0.80)
        top = df_v[df_v["views"] >= thr]
        n_top = len(top)
        def pct_top(s):
            return round(100.0 * s.sum() / n_top, 1) if n_top else 0
        top_metrics = {
            "n": n_top,
            "threshold_views": int(thr),
            "avg_text_length": int(top["text_length"].dropna().mean()) if top["text_length"].notna().any() else None,
            "median_text_length": int(top["text_length"].dropna().median()) if top["text_length"].notna().any() else None,
            "q25_text_length": int(top["text_length"].dropna().quantile(0.25)) if top["text_length"].notna().any() else None,
            "q75_text_length": int(top["text_length"].dropna().quantile(0.75)) if top["text_length"].notna().any() else None,
            "avg_paragraphs": round(top["paragraphs_count"].dropna().mean(), 1) if top["paragraphs_count"].notna().any() else None,
            "median_paragraphs": int(top["paragraphs_count"].dropna().median()) if top["paragraphs_count"].notna().any() else None,
            "pct_with_dialog": pct_top(top["tx_has_dialog"]),
            "pct_with_rub": pct_top(top["tx_has_rub"]),
            "pct_ends_with_question": pct_top(top["tx_ends_q"]),
        }
    else:
        top_metrics = {"n": 0}

    out = {"all": all_metrics, "top20pct_by_views": top_metrics}
    with open(os.path.join(OUT_DIR, "text_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out, df


# ================================================================ ШАГ 4
def step4_metrics(df):
    df_v = df[df["views"].notna()].copy()
    views = df_v["views"].astype(int)
    distribution = {
        "n": len(views),
        "min": int(views.min()),
        "max": int(views.max()),
        "median": int(views.median()),
        "q25": int(views.quantile(0.25)),
        "q75": int(views.quantile(0.75)),
        "top10_threshold": int(views.quantile(0.90)),
    }

    def corr(x, y, name):
        x = pd.to_numeric(x, errors="coerce")
        y = pd.to_numeric(y, errors="coerce")
        mask = x.notna() & y.notna()
        if mask.sum() < 3:
            return {"name": name, "spearman": None, "pearson": None, "n": int(mask.sum())}
        r_s, p_s = sp_stats.spearmanr(x[mask], y[mask])
        r_p, p_p = sp_stats.pearsonr(x[mask], y[mask])
        return {"name": name,
                "spearman": round(float(r_s), 3),
                "pearson": round(float(r_p), 3),
                "n": int(mask.sum())}

    # корреляции
    corrs = []
    corrs.append(corr(df_v["text_length"], df_v["views"], "text_length_vs_views"))
    corrs.append(corr(df_v["tk_chars"], df_v["views"], "title_chars_vs_views"))
    corrs.append(corr(df_v["tk_words"], df_v["views"], "title_words_vs_views"))
    corrs.append(corr(df_v["time_to_read"], df_v["views"], "time_to_read_vs_views"))

    # для бинарных — point-biserial (==pearson для 0/1)
    corrs.append(corr(df_v["tk_has_digit"].astype(int), df_v["views"], "title_has_digit_vs_views"))
    corrs.append(corr(df_v["tk_has_rub"].astype(int), df_v["views"], "title_has_rub_vs_views"))
    corrs.append(corr(df_v["tk_has_question"].astype(int), df_v["views"], "title_has_question_vs_views"))
    corrs.append(corr(df_v["tk_has_hero"].astype(int), df_v["views"], "title_has_hero_vs_views"))
    corrs.append(corr(df_v["tx_has_dialog"].astype(int), df_v["views"], "text_has_dialog_vs_views"))
    corrs.append(corr(df_v["tx_has_rub"].astype(int), df_v["views"], "text_has_rub_vs_views"))

    # каналы — лучший по медиане views
    by_ch = df_v.groupby("channel_slug").agg(
        articles=("views", "count"),
        median_views=("views", "median"),
        mean_views=("views", "mean"),
    ).reset_index().sort_values("median_views", ascending=False)
    best_channels = by_ch.head(5).to_dict(orient="records")

    # топ-10 статей
    top10 = df_v.nlargest(10, "views")[["id", "channel_slug", "title", "views", "likes", "comments"]]
    top10_list = top10.to_dict(orient="records")

    out = {
        "distribution": distribution,
        "correlations": corrs,
        "best_channels_by_median_views": best_channels,
        "top10_by_views": top10_list,
    }
    with open(os.path.join(OUT_DIR, "metrics_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out


# ================================================================ ШАГ 5
def step5_comparison(df):
    """Сравниваем наш канал с конкурентами.

    Стратегия:
      - наши статьи из research.db: ищем канал с slug='our'/'our_dzen'/'vzoprodengi_our'
        или channel_id специально, или (запасной) берём записи с dzen_id
        вида 'our_*' (если такие есть).
      - наши статьи из data/analysis_source/our_articles.txt: парсим заголовки.
    """
    # 1) пытаемся найти в research.db
    our_db = df[df["title"].str.contains(r"^Самая дорогая строка|^Кнопка", case=False, regex=True, na=False)]
    # грубый фильтр: статьи из нашего канала — те, что в our_articles.txt по id
    # (id=40, 31, 30, 29, 28 в первой партии)
    # парсим наши id из файла
    our_ids = []
    if os.path.exists(OUR_TXT):
        with open(OUR_TXT, encoding="utf-8") as fh:
            txt = fh.read()
        for m in re.finditer(r"### OUR #\d+ \| id=(\d+)", txt):
            our_ids.append(int(m.group(1)))
    our_db = df[df["id"].isin(our_ids)].copy() if our_ids else pd.DataFrame()

    # 2) парсим заголовки из our_articles.txt (на случай, если в БД их нет)
    our_titles = []
    if os.path.exists(OUR_TXT):
        with open(OUR_TXT, encoding="utf-8") as fh:
            txt = fh.read()
        for m in re.finditer(r"### TITLE:\s*(.+)", txt):
            our_titles.append(m.group(1).strip())

    n_our_db = len(our_db)
    n_our_titles = len(our_titles)

    if n_our_db > 0:
        # используем данные из БД (там есть text_length, views, и т.д.)
        df_o = our_db.copy()
        source = "research.db (id=" + ",".join(map(str, our_ids[:5])) + (",..." if len(our_ids) > 5 else "") + ")"
    elif n_our_titles > 0:
        # фоллбэк: только заголовки
        df_o = pd.DataFrame({"title": our_titles, "text": [""] * len(our_titles),
                              "text_length": [None] * len(our_titles),
                              "views": [None] * len(our_titles),
                              "likes": [None] * len(our_titles),
                              "comments": [None] * len(our_titles)})
        source = "our_articles.txt (заголовки без БД)"
    else:
        df_o = pd.DataFrame()

    # конкуренты — все из research.db, кроме наших id
    df_c = df[~df["id"].isin(our_ids)].copy() if our_ids else df.copy()

    def metrics_block(d, has_full=True):
        if len(d) == 0:
            return None
        m = {}
        m["n"] = int(len(d))
        if "title" in d.columns:
            tm = d["title"].apply(title_metrics)
            n = len(tm)
            d2 = pd.DataFrame(list(tm))
            m["pct_with_digit"] = round(100.0 * d2["has_digit"].sum() / n, 1) if n else 0
            m["pct_with_question"] = round(100.0 * d2["has_question"].sum() / n, 1) if n else 0
            m["pct_with_hero"] = round(100.0 * d2["has_hero"].sum() / n, 1) if n else 0
            m["pct_with_rub"] = round(100.0 * d2["has_rub"].sum() / n, 1) if n else 0
            m["median_title_words"] = int(d2["word_count"].median())
            m["median_title_chars"] = int(d2["char_count"].median())
        if has_full and "text_length" in d.columns and d["text_length"].notna().any():
            tl = pd.to_numeric(d["text_length"], errors="coerce").dropna()
            m["median_text_length"] = int(tl.median())
            m["avg_text_length"] = int(tl.mean())
        if has_full and "paragraphs_count" in d.columns and d["paragraphs_count"].notna().any():
            ps = pd.to_numeric(d["paragraphs_count"], errors="coerce").dropna()
            m["median_paragraphs"] = int(ps.median())
        if has_full and "text" in d.columns:
            txm = d["text"].apply(text_metrics)
            d_tx = pd.DataFrame(list(txm.dropna()))
            n_tx = len(d_tx)
            if n_tx:
                m["pct_with_dialog"] = round(100.0 * d_tx["has_dialog"].sum() / n_tx, 1)
                m["pct_with_rub_in_text"] = round(100.0 * d_tx["has_rub"].sum() / n_tx, 1)
        if has_full and "views" in d.columns and d["views"].notna().any():
            vs = pd.to_numeric(d["views"], errors="coerce").dropna()
            m["median_views"] = int(vs.median())
        if has_full and "time_to_read" in d.columns and d["time_to_read"].notna().any():
            ttr = pd.to_numeric(d["time_to_read"], errors="coerce").dropna()
            m["median_time_to_read_sec"] = int(ttr.median())
        return m

    out = {
        "source": source,
        "our_article_ids": our_ids,
        "n_our_titles_in_txt": n_our_titles,
        "our": metrics_block(df_o, has_full=(n_our_db > 0)),
        "competitors": metrics_block(df_c, has_full=True),
    }
    with open(os.path.join(OUT_DIR, "comparison.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out


# ================================================================ main
def main():
    print("[load] читаю research.db...")
    df = load_df()
    print(f"  загружено: {len(df)} статей, {df['channel_id'].nunique()} каналов")
    # подготовим колонки для корреляций ШАГ 2/3
    df["title_m"] = df["title"].apply(title_metrics)
    df["tk_has_digit"] = df["title_m"].apply(lambda m: m["has_digit"] if m else False)
    df["tk_has_question"] = df["title_m"].apply(lambda m: m["has_question"] if m else False)
    df["tk_has_hero"] = df["title_m"].apply(lambda m: m["has_hero"] if m else False)
    df["tk_has_rub"] = df["title_m"].apply(lambda m: m["has_rub"] if m else False)
    df["tk_words"] = df["title_m"].apply(lambda m: m["word_count"] if m else 0)
    df["tk_chars"] = df["title_m"].apply(lambda m: m["char_count"] if m else 0)
    df["text_m"] = df["text"].apply(text_metrics)
    df["tx_has_dialog"] = df["text_m"].apply(lambda m: m["has_dialog"] if m else False)
    df["tx_has_rub"] = df["text_m"].apply(lambda m: m["has_rub"] if m else False)
    df["tx_ends_q"] = df["text_m"].apply(lambda m: m["ends_with_question"] if m else False)

    print("[step1] статистика по каналам...")
    s1 = step1_channels(df)
    print(f"  → {OUT_DIR}/channels_stats.json ({len(s1['channels'])} каналов)")

    print("[step2] анализ заголовков...")
    s2, _ = step2_titles(df)
    print(f"  → {OUT_DIR}/titles_stats.json")

    print("[step3] анализ текстов...")
    s3, _ = step3_texts(df)
    print(f"  → {OUT_DIR}/text_stats.json")

    print("[step4] метрики и корреляции...")
    s4 = step4_metrics(df)
    print(f"  → {OUT_DIR}/metrics_stats.json")

    print("[step5] сравнение наш vs конкуренты...")
    s5 = step5_comparison(df)
    print(f"  → {OUT_DIR}/comparison.json")

    print("\n[done] все JSON-файлы в", OUT_DIR)


if __name__ == "__main__":
    main()
