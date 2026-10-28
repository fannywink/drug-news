"""
마약류 뉴스 수집·요약 (1단계)

- 네이버 클라우드 NAVER API HUB의 뉴스 검색 API로 최근 24시간 기사를 수집함
- 지정한 10개 매체 기사만 남기고 중복을 제거함
- Claude API로 관련성 판별 → 사건별 묶기 → 분야별 요약 → 약사 시사점 코멘트를 작성함
- 결과는 docs/날짜/ 폴더에 summary.json, briefing.txt, 카드뉴스 PNG, 링크 모음, 웹페이지(index.html)로 저장함

실행 전 환경변수 설정 필요:
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, ANTHROPIC_API_KEY
"""

import html
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import anthropic
import requests

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
KST = timezone(timedelta(hours=9))
HOURS_BACK = 24  # 최근 몇 시간 기사를 모을지
MODEL = "claude-sonnet-5-5"  # 사용할 Claude 모델 (docs.claude.com에서 최신 이름 확인)
OUTPUT_DIR = "docs"  # GitHub Pages로 공개되는 폴더 (날짜별 하위 폴더에 저장)

# 대상 매체: 도메인 → 매체명
PRESS = {
    "donga.com": "동아일보",
    "joongang.co.kr": "중앙일보",
    "khan.co.kr": "경향신문",
    "hani.co.kr": "한겨레",
    "yna.co.kr": "연합뉴스",
    "jtbc.co.kr": "JTBC",
    "ytn.co.kr": "YTN",
    "dailypharm.com": "데일리팜",
    "kpanews.co.kr": "약사공론",
    "yakup.com": "약업신문",
}

# 검색 키워드 (필요하면 추가·삭제)
KEYWORDS = [
    "마약", "마약류", "마약사범", "필로폰", "대마", "펜타닐", "케타민",
    "프로포폴", "졸피뎀", "향정신성", "의료용 마약류", "마약류통합관리시스템",
    "메틸페니데이트", "약물 오남용",
]

# 네이버 검색 API는 2026년 하반기부터 네이버 클라우드 "NAVER API HUB"에서 발급·제공됨
NAVER_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"


# ─────────────────────────────────────────
# 1. 수집
# ─────────────────────────────────────────
def clean(text: str) -> str:
    """네이버 응답의 <b> 태그와 HTML 엔티티를 제거함"""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def press_of(url: str):
    """기사 URL의 도메인으로 매체명을 찾음 (대상 매체가 아니면 None)"""
    host = urlparse(url).netloc.lower()
    for domain, name in PRESS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def search_news(query: str, cutoff: datetime) -> list:
    headers = {
        "X-NCP-APIGW-API-KEY-ID": os.environ["NAVER_CLIENT_ID"],   # API HUB의 Client ID
        "X-NCP-APIGW-API-KEY": os.environ["NAVER_CLIENT_SECRET"],  # API HUB의 Client Secret
    }
    found = []
    for start in range(1, 1001, 100):  # 네이버 API는 최대 1000건까지 조회 가능
        r = requests.get(
            NAVER_URL,
            headers=headers,
            params={"query": query, "display": 100, "start": start, "sort": "date", "format": "json"},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            break

        reached_old = False
        for it in items:
            pub = parsedate_to_datetime(it["pubDate"])
            if pub < cutoff:
                reached_old = True
                continue
            url = it.get("originallink") or it.get("link")
            press = press_of(url)
            if not press:
                continue
            found.append({
                "press": press,
                "title": clean(it["title"]),
                "description": clean(it["description"]),
                "url": url,
                "published": pub.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            })
        if reached_old or len(items) < 100:
            break
        time.sleep(0.1)
    return found


def collect() -> list:
    cutoff = datetime.now(KST) - timedelta(hours=HOURS_BACK)
    by_url, seen_titles = {}, set()

    for kw in KEYWORDS:
        for a in search_news(kw, cutoff):
            title_key = (a["press"], re.sub(r"\W", "", a["title"]))
            if a["url"] in by_url or title_key in seen_titles:
                continue
            by_url[a["url"]] = a
            seen_titles.add(title_key)

    articles = sorted(by_url.values(), key=lambda x: x["published"], reverse=True)

    # 매체별 수집 건수 확인 (0건 매체는 RSS 보완 검토)
    counts = Counter(a["press"] for a in articles)
    print(f"\n[수집] 총 {len(articles)}건")
    for name in PRESS.values():
        print(f"  - {name}: {counts.get(name, 0)}건")
    return articles


# ─────────────────────────────────────────
# 2. 필터링·요약 (Claude)
# ─────────────────────────────────────────
SYSTEM_PROMPT = """너는 경기도약사회 마약퇴치사업본부에서 회원 약사들에게 보내는 일일 마약류 뉴스 브리핑을 작성한다.
독자는 지역약국 약사이며, 뉴스를 약사의 업무와 역할 관점에서 해석해 주는 것이 목적이다.
반드시 JSON만 출력하고, 설명이나 코드블록 표시(```)는 붙이지 않는다."""

USER_PROMPT = """아래는 최근 24시간 동안 수집한 기사 목록(제목·요약문)이다.

[작성 규칙]
1. 실제 마약류와 관련된 기사만 포함한다. 불법 마약, 의료용 마약류·향정신성의약품 오남용, 관련 정책·단속·수사·예방·치료·재활이 해당한다.
   '마약김밥', '마약 같은 매력'처럼 비유적으로 쓰인 기사는 제외한다.
2. 같은 사건·사안을 다룬 여러 기사는 하나로 묶고, 출처는 모두 sources에 넣는다.
3. 분류는 "단속·사건", "정책·제도", "의료용 마약류", "예방·치료·재활", "기타" 중에서 고른다. 해당 기사가 없는 분류는 생략한다.
4. summary는 제공된 제목·요약문에 있는 사실만 사용하고 추측하지 않는다. 2문장, 120자 이내로, 기사 문장을 그대로 옮기지 말고 새로 구성한다.
5. comment는 이 뉴스가 약사에게 주는 의미를 2문장, 100자 이내로 쓴다. 기사 내용을 되풀이하지 말고 다음 관점 중 맞는 것을 골라 실무적으로 쓴다.
   - 처방 확인·조제·복약상담 시 주의할 점
   - 마약류 보관·재고·보고 등 약국 관리 업무
   - 환자·보호자에게 안내할 내용
   - 예방교육·지역사회에서 약사가 할 수 있는 역할
   주의: 기사에 없는 법 조항·처벌 수위·수치·제도명을 지어내지 않는다. 확실하지 않은 제도는 일반적인 표현으로 쓴다.
   특정인·직군을 비난하거나 공포를 조장하지 않고, 차분하고 제안하는 어조(~합니다/~해 주세요)로 쓴다.
6. 각 분류 안에서 중요도 순으로 정렬한다. 약사·약국과 직접 관련된 사안은 pharmacy를 true로 한다.
7. headline에는 오늘 가장 중요한 이슈를 한 문장(30자 이내)으로 쓴다.
8. daily_comment에는 오늘 뉴스 전체를 관통하는 약사에게 주는 메시지를 2문장, 120자 이내로 쓴다.

[출력 형식]
{{
  "headline": "오늘의 핵심 한 줄",
  "categories": [
    {{
      "name": "분류명",
      "items": [
        {{
          "title": "사안 제목(직접 작성, 25자 이내)",
          "summary": "2문장 요약",
          "comment": "약사에게 주는 의미 2문장",
          "pharmacy": false,
          "sources": [{{"press": "매체명", "url": "기사 URL"}}]
        }}
      ]
    }}
  ],
  "daily_comment": "오늘의 약사 한마디",
  "excluded_count": 제외한_기사_수
}}

[기사 목록]
{articles}
"""


def summarize(articles: list) -> dict:
    if not articles:
        return {"headline": "오늘은 대상 매체의 마약류 관련 기사가 없습니다.",
                "categories": [], "daily_comment": "", "excluded_count": 0}

    payload = [
        {"id": i, "press": a["press"], "title": a["title"],
         "description": a["description"], "url": a["url"]}
        for i, a in enumerate(articles)
    ]
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_PROMPT.format(
            articles=json.dumps(payload, ensure_ascii=False, indent=1))}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    return json.loads(text)


# ─────────────────────────────────────────
# 3. 확인용 텍스트
# ─────────────────────────────────────────
def to_text(summary: dict, date_str: str) -> str:
    lines = [f"■ 마약류 뉴스 브리핑 ({date_str})", "", f"▶ {summary['headline']}", ""]
    for cat in summary.get("categories", []):
        lines.append(f"[{cat['name']}]")
        for item in cat["items"]:
            mark = " 💊약국" if item.get("pharmacy") else ""
            press = ", ".join(s["press"] for s in item["sources"])
            lines.append(f"· {item['title']}{mark}")
            lines.append(f"  {item['summary']}")
            lines.append(f"  → 약사에게 주는 의미: {item.get('comment', '')}")
            lines.append(f"  ({press})")
        lines.append("")
    if summary.get("daily_comment"):
        lines.append(f"■ 오늘의 약사 한마디\n{summary['daily_comment']}")
        lines.append("")
    lines.append(f"※ 관련 없는 기사 {summary.get('excluded_count', 0)}건 제외")
    return "\n".join(lines)


# ─────────────────────────────────────────
# 실행
# ─────────────────────────────────────────
def update_archive_index():
    """docs/index.html에 날짜별 브리핑 목록을 만듦"""
    days = sorted((d for d in os.listdir(OUTPUT_DIR)
                   if d.isdigit() and os.path.exists(os.path.join(OUTPUT_DIR, d, "index.html"))), reverse=True)
    rows = "".join(f'<li><a href="{d}/">{d[:4]}.{d[4:6]}.{d[6:]}</a></li>' for d in days)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta name="robots" content="noindex"><title>약사가 읽는 마약류 뉴스</title>'
                '<style>body{font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 20px;line-height:1.8}'
                'a{color:#123C36}</style></head><body><h1>약사가 읽는 마약류 뉴스</h1>'
                f'<ul>{rows}</ul></body></html>')


def main():
    today = datetime.now(KST)
    date_str = today.strftime("%Y.%m.%d")
    day_dir = os.path.join(OUTPUT_DIR, today.strftime("%Y%m%d"))
    os.makedirs(day_dir, exist_ok=True)

    articles = collect()
    summary = summarize(articles)
    summary["date"] = date_str

    text = to_text(summary, date_str)
    with open(os.path.join(day_dir, "briefing.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)

    # 카드뉴스·링크 모음·웹페이지 생성
    from make_cardnews import render
    render(summary, day_dir)

    with open(os.path.join(day_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    update_archive_index()
    print(f"\n[저장] {day_dir}")


if __name__ == "__main__":
    main()
