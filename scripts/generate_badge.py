"""Generate an SVG badge of Duolingo CEFR levels and scores per language.

Reads the Duolingo JWT from the DUOLINGO_JWT environment variable and writes
the badge to the path given as the first argument (default: duolingo.svg).
"""

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://www.duolingo.com/2017-06-30"
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
HEIGHT = 120
PADDING = 10


def user_id_from_jwt(jwt):
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def get(path, jwt):
    request = urllib.request.Request(
        f"{API}/{path}",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Cookie": f"jwt_token={jwt}",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


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


def fetch_languages(jwt):
    user_id = user_id_from_jwt(jwt)
    courses = get(f"users/{user_id}?fields=courses", jwt)["courses"]
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


def render_svg(languages):
    width = PADDING * 2 + COLUMN_WIDTH * max(len(languages), 1)
    columns = []
    for i, language in enumerate(languages):
        x = PADDING + COLUMN_WIDTH * i + COLUMN_WIDTH / 2
        title = escape(language["title"])
        if language["flag"]:
            title_width = text_width(language["title"])
            title_x = x - (title_width + FLAG_GAP + FLAG_WIDTH) / 2
            flag_x = title_x + title_width + FLAG_GAP
            header = (
                f'''  <text x="{title_x:.1f}" y="32" class="title start">{title}</text>
  <image x="{flag_x:.1f}" y="{32 - 13}" width="{FLAG_WIDTH}" height="{FLAG_HEIGHT}" href="{language["flag"]}"/>'''
            )
        else:
            header = f'  <text x="{x}" y="32" class="title">{title}</text>'
        columns.append(
            f"""{header}
  <text x="{x}" y="70" class="cefr">{escape(language["cefr"])}</text>
  <text x="{x}" y="94" class="score">{language["score"]}/{language["max_score"]}</text>
  <text x="{x}" y="108" class="label">Duolingo Score</text>"""
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{HEIGHT}" viewBox="0 0 {width} {HEIGHT}">
  <style>
    text {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; text-anchor: middle; }}
    .title {{ font-size: 14px; font-weight: 600; fill: #4b4b4b; }}
    .start {{ text-anchor: start; }}
    .cefr {{ font-size: 30px; font-weight: 800; fill: #58cc02; }}
    .score {{ font-size: 14px; font-weight: 700; fill: #1cb0f6; }}
    .label {{ font-size: 9px; fill: #777777; }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{HEIGHT - 1}" rx="12" fill="#ffffff" stroke="#e5e5e5"/>
{chr(10).join(columns)}
</svg>
"""


def main():
    jwt = os.environ["DUOLINGO_JWT"]
    output = sys.argv[1] if len(sys.argv) > 1 else "duolingo.svg"
    languages = fetch_languages(jwt)
    with open(output, "w") as f:
        f.write(render_svg(languages))
    for language in languages:
        print(f"{language['title']}: {language['cefr']} {language['score']}/{language['max_score']}")


if __name__ == "__main__":
    main()
