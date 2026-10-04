"""Daily digest of fastest-growing GitHub repos -> digest.md + README.md (shown on the repo main page).

Velocity = stars gained since yesterday's snapshot (data/stars.json).
Repos not in the snapshot yet (first run / newly found) get an estimate: stars / age in days.
Each repo gets a Russian card written by GitHub Models from its README; falls back to the translated description.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/search/repositories"
SNAP = "data/stars.json"
TOP = 15
MODELS = "https://models.github.ai/inference/chat/completions"
MODEL = "openai/gpt-4.1-mini"
README_CHARS = 12000  # free tier caps a request at ~8k input tokens
FIELDS = (
    ("what", "Что это"),
    ("problem", "Какую проблему решает"),
    ("audience", "Для кого"),
    ("maturity", "Зрелость"),
    ("open_if", "Стоит открыть, если"),
)
PROMPT = """Ты пишешь карточку GitHub-репозитория для ежедневного дайджеста, чтобы читатель за 10 секунд понял, стоит ли его открывать.
По README и описанию верни JSON строго с ключами:
"what" - что это, одно предложение;
"problem" - какую конкретную проблему решает и чем лучше привычных способов;
"audience" - для кого;
"maturity" - зрелость: прототип / ранняя версия / готово к работе, и как поставить (pip, npm, docker, веб, ...);
"open_if" - в каких случаях стоит открыть.
Пиши по-русски, просто и конкретно, без маркетинга, каждое поле до 25 слов. Названия продуктов не переводи. Если данных мало, так и напиши."""


def gh(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def search(q):
    url = f"{API}?{urllib.parse.urlencode({'q': q, 'sort': 'stars', 'order': 'desc', 'per_page': 100})}"
    return json.loads(gh(url))["items"]


def readme(name):
    try:
        return gh(f"https://api.github.com/repos/{name}/readme", "application/vnd.github.raw").decode("utf-8", "replace")
    except Exception:
        return ""


def summarize(name, desc, text):
    """Card fields from GitHub Models, or None on any failure."""
    body = json.dumps({
        "model": MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"Репозиторий: {name}\nОписание: {desc}\n\nREADME:\n{text[:README_CHARS]}"},
        ],
    }).encode()
    req = urllib.request.Request(MODELS, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            card = json.loads(json.load(r)["choices"][0]["message"]["content"])
        return card if all(card.get(k) for k, _ in FIELDS) else None
    except Exception as e:
        print(f"summarize {name}: {e}", file=sys.stderr)
        return None


def card(i, name, r, s, est, age, fields):
    lines = [
        f"### {i}. [{name}]({r['html_url']})",
        f"⭐ {r['stargazers_count']:,} · {'~' if est else '+'}{s:,.0f}/день · {age} дн · {r['language'] or '-'}".replace(",", " "),
        "",
    ]
    if fields:
        lines += [f"- **{label}:** {' '.join(str(fields[k]).split())}" for k, label in FIELDS]
    else:
        lines.append(f"- **Что это:** {' '.join(translate(r['description'] or 'нет описания').split())}")
    return lines + [""]


def translate(text):
    """To Russian via free MyMemory API; on any failure keep the original."""
    if not text:
        return text
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({"q": text[:500], "langpair": "autodetect|ru"})
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.load(r)
        return d["responseData"]["translatedText"] if d.get("responseStatus") == 200 else text
    except Exception:
        return text


def score(stars, prev, age_days):
    return stars - prev if prev is not None else stars / max(age_days, 1)


def main():
    now = datetime.now(timezone.utc)
    # ponytail: only repos <180d old are watched; old giants rarely "explode". Widen the query if needed.
    queries = (
        f"created:>{(now - timedelta(days=30)).date()} stars:>100",
        f"created:>{(now - timedelta(days=180)).date()} stars:>1000",
    )
    repos = {r["full_name"]: r for q in queries for r in search(q)}

    try:
        with open(SNAP) as f:
            prev = json.load(f)
    except FileNotFoundError:
        prev = {}

    rows = []
    for name, r in repos.items():
        age = (now - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).days
        p = prev.get(name)
        rows.append((score(r["stargazers_count"], p, age), p is None, name, r, age))
    rows.sort(key=lambda x: -x[0])

    out = [
        f"# Быстрорастущие репозитории GitHub - {now.date()}",
        "",
        "`+N/день` = прирост звёзд за 24 ч. `~N/день` = оценка (звёзды / возраст), репозиторий ещё не отслеживался.",
        "",
    ]
    for i, (s, est, name, r, age) in enumerate(rows[:TOP], 1):
        if i > 1:
            time.sleep(5)  # free tier: 15 requests/min
        fields = summarize(name, r["description"] or "", readme(name))
        out += card(i, name, r, s, est, age, fields)

    for path in ("digest.md", "README.md"):
        with open(path, "w") as f:
            f.write("\n".join(out) + "\n")
    os.makedirs("data", exist_ok=True)
    with open(SNAP, "w") as f:
        json.dump({n: r["stargazers_count"] for n, r in repos.items()}, f)


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert score(150, 100, 5) == 50
        assert score(150, None, 5) == 30
        assert score(10, None, 0) == 10
        r = {"html_url": "u", "stargazers_count": 30548, "language": "Python", "description": "d"}
        c = card(2, "a/b", r, 1909, True, 16, {k: f"{k}\ntext" for k, _ in FIELDS})
        assert c[1] == "⭐ 30 548 · ~1 909/день · 16 дн · Python", c[1]
        assert c[3] == "- **Что это:** what text", c[3]
        print("ok")
    else:
        main()
