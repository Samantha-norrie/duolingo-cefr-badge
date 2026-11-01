"""Generate an SVG badge of a Duolingo profile and CEFR levels per language.

The top row shows the avatar, streak, total XP, current league and leaderboard
top 3 finishes; below
it is a column per language with its CEFR level and Duolingo Score.

Reads the Duolingo JWT from the DUOLINGO_JWT environment variable and writes
light and dark badges to the paths given as the first and second arguments
(default: duolingo.svg and duolingo-dark.svg).
"""

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://www.duolingo.com/2017-06-30"
LEADERBOARD_API = (
    "https://duolingo-leaderboards-prod.duolingo.com/leaderboards/"
    "7d9f5dd1-8423-491a-91f2-2532052038ce"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MIN_SCORE = 7

# Duolingo flag SVGs, named by learning language code.
FLAGS_DIR = Path(__file__).resolve().parent.parent / "assets" / "flags"
FLAG_WIDTH = 21
FLAG_HEIGHT = 16
FLAG_GAP = 6

COLUMN_WIDTH = 140
PADDING = 10

# Profile row above the language columns.
AVATAR_SIZE = 72
STAT_WIDTH = 112
PROFILE_HEIGHT = 96
HEIGHT = PROFILE_HEIGHT + 120

# Colors per GitHub theme; the README picks one with prefers-color-scheme.
THEMES = {
    "light": {
        "background": "#ffffff",
        "border": "#e5e5e5",
        "title": "#4b4b4b",
        "label": "#777777",
    },
    "dark": {
        "background": "#0d1117",
        "border": "#30363d",
        "title": "#f0f6fc",
        "label": "#9198a1",
    },
}


def user_id_from_jwt(jwt):
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def fetch(url, jwt=None):
    headers = {"User-Agent": USER_AGENT}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
        headers["Cookie"] = f"jwt_token={jwt}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def get(path, jwt):
    return json.loads(fetch(f"{API}/{path}", jwt))


def flag_data_uri(language_code):
    """Flag SVG as a data URI, since SVGs rendered as images can't load URLs."""
    path = FLAGS_DIR / f"{language_code}.svg"
    if not path.exists():
        return None
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def text_width(text, font_size=14):
    """Rough rendered width of semibold sans-serif text, for centering."""
    narrow, wide = set("fijlrtI "), set("mwMW")
    width = 0
    for char in text:
        if char in narrow:
            width += 0.32
        elif char in wide:
            width += 0.85
        elif char.isupper():
            width += 0.68
        else:
            width += 0.56
    return width * font_size


def achieved_cefr(course):
    """CEFR level of the last fully completed path section."""
    if course["scoreMetadata"].get("supportType") == "NON_CEFR_ALIGNED":
        return "N/A"
    achieved = "Pre-A1"
    for section in sorted(course.get("pathSectioned", []), key=lambda s: s["index"]):
        total = section.get("totalUnits", 0)
        if total == 0 or section.get("completedUnits", 0) < total:
            break
        level = (section.get("cefr") or {}).get("level")
        if level and level != "INTRO":
            achieved = level
    return achieved


def fetch_profile(user, jwt):
    """Avatar (as a data URI), streak, total XP, league and top 3 finishes."""
    # picture is a protocol-relative CDN URL; sizes are path suffixes.
    avatar = fetch(f"https:{user['picture']}/xlarge")
    leaderboard = json.loads(fetch(f"{LEADERBOARD_API}/users/{user['id']}", jwt))
    # tier indexes league_ids; it's missing when not in a league this week.
    tier = leaderboard.get("tier")
    leagues = leaderboard["league_ids"]
    return {
        "avatar": "data:image/png;base64," + base64.b64encode(avatar).decode(),
        "streak": user["streak"],
        "total_xp": user["totalXp"],
        "league": leagues[tier] if tier is not None and 0 <= tier < len(leagues) else "None",
        "top_three": leaderboard["stats"]["top_three_finishes"],
    }


def fetch_languages(user_id, courses, jwt):
    languages = []
    for summary in courses:
        course = get(f"users/{user_id}/courses/{summary['id']}", jwt)
        score = course["scoreMetadata"]
        if score["reachedScore"] < MIN_SCORE:
            continue
        languages.append(
            {
                "title": summary["title"],
                "flag": flag_data_uri(summary["learningLanguage"]),
                "cefr": achieved_cefr(course),
                "score": score["reachedScore"],
                "max_score": score["pathEndingScore"],
            }
        )
    return sorted(languages, key=lambda language: language["score"], reverse=True)


def render_profile(profile, colors, width):
    avatar_x = PADDING + 14
    avatar_y = (PROFILE_HEIGHT - AVATAR_SIZE) / 2
    radius = AVATAR_SIZE / 2
    parts = [
        f'''  <clipPath id="avatar"><circle cx="{avatar_x + radius}" cy="{avatar_y + radius}" r="{radius}"/></clipPath>
  <image x="{avatar_x}" y="{avatar_y}" width="{AVATAR_SIZE}" height="{AVATAR_SIZE}" href="{profile["avatar"]}" clip-path="url(#avatar)"/>'''
    ]
    stats = [
        (f"{profile['streak']:,}", "Day streak", "streak"),
        (f"{profile['total_xp']:,}", "Total XP", "xp"),
        (escape(profile["league"]), "Current league", "league"),
        (f"{profile['top_three']:,}", "Top 3 finishes", "top-three"),
    ]
    for i, (value, label, css_class) in enumerate(stats):
        x = avatar_x + AVATAR_SIZE + 10 + STAT_WIDTH * i + STAT_WIDTH / 2
        parts.append(
            f'''  <text x="{x}" y="50" class="stat {css_class}">{value}</text>
  <text x="{x}" y="66" class="stat-label">{label}</text>'''
        )
    parts.append(
        f'  <line x1="{PADDING}" y1="{PROFILE_HEIGHT}" x2="{width - PADDING}" y2="{PROFILE_HEIGHT}" stroke="{colors["border"]}"/>'
    )
    return "\n".join(parts)


def render_svg(profile, languages, theme):
    colors = THEMES[theme]
    profile_width = PADDING * 2 + 14 + AVATAR_SIZE + 10 + STAT_WIDTH * 4
    width = max(PADDING * 2 + COLUMN_WIDTH * max(len(languages), 1), profile_width)
    profile_svg = render_profile(profile, colors, width)
    top = PROFILE_HEIGHT
    columns = []
    for i, language in enumerate(languages):
        x = PADDING + COLUMN_WIDTH * i + COLUMN_WIDTH / 2
        title = escape(language["title"])
        if language["flag"]:
            title_width = text_width(language["title"])
            flag_x = x - (FLAG_WIDTH + FLAG_GAP + title_width) / 2
            title_x = flag_x + FLAG_WIDTH + FLAG_GAP
            header = (
                f'''  <image x="{flag_x:.1f}" y="{top + 32 - 13}" width="{FLAG_WIDTH}" height="{FLAG_HEIGHT}" href="{language["flag"]}"/>
  <text x="{title_x:.1f}" y="{top + 32}" class="title start">{title}</text>'''
            )
        else:
            header = f'  <text x="{x}" y="{top + 32}" class="title">{title}</text>'
        columns.append(
            f"""{header}
  <text x="{x}" y="{top + 70}" class="cefr">{escape(language["cefr"])}</text>
  <text x="{x}" y="{top + 94}" class="score">{language["score"]}/{language["max_score"]}</text>
  <text x="{x}" y="{top + 108}" class="label">Duolingo Score</text>"""
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{HEIGHT}" viewBox="0 0 {width} {HEIGHT}">
  <style>
    text {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; text-anchor: middle; }}
    .title {{ font-size: 14px; font-weight: 600; fill: {colors['title']}; }}
    .start {{ text-anchor: start; }}
    .cefr {{ font-size: 30px; font-weight: 800; fill: #58cc02; }}
    .score {{ font-size: 14px; font-weight: 700; fill: #1cb0f6; }}
    .label {{ font-size: 9px; fill: {colors['label']}; }}
    .stat {{ font-size: 22px; font-weight: 800; }}
    .streak {{ fill: #ff9600; }}
    .xp {{ fill: #ffc800; }}
    .league {{ fill: #ce82ff; }}
    .top-three {{ fill: #ff86d0; }}
    .stat-label {{ font-size: 11px; fill: {colors['label']}; }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{HEIGHT - 1}" rx="12" fill="{colors['background']}" stroke="{colors['border']}"/>
{profile_svg}
{chr(10).join(columns)}
</svg>
"""


def main():
    jwt = os.environ["DUOLINGO_JWT"]
    outputs = {
        "light": sys.argv[1] if len(sys.argv) > 1 else "duolingo.svg",
        "dark": sys.argv[2] if len(sys.argv) > 2 else "duolingo-dark.svg",
    }
    user_id = user_id_from_jwt(jwt)
    user = get(f"users/{user_id}?fields=id,picture,totalXp,courses", jwt)
    profile = fetch_profile(user, jwt)
    languages = fetch_languages(user_id, user["courses"], jwt)
    for theme, output in outputs.items():
        with open(output, "w") as f:
            f.write(render_svg(profile, languages, theme))
    print(
        f"Streak: {profile['streak']}, total XP: {profile['total_xp']}, "
        f"league: {profile['league']}, top 3 finishes: {profile['top_three']}"
    )
    for language in languages:
        print(f"{language['title']}: {language['cefr']} {language['score']}/{language['max_score']}")


if __name__ == "__main__":
    main()
