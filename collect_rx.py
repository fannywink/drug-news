"""
의료용 마약류 브리핑 (주 3회: 월·수·금)

- 의료용 마약류 오남용, 트라마돌·프레가발린처럼 국내에서는 마약류가 아니지만 해외에서는
  마약류로 관리되는 약물, 그리고 수면유도제·감기약·기침약 등 일반의약품 오남용(오버도즈)에 관한
  기사만 골라 카드뉴스로 만듦
- 수집 기간: 월요일은 금요일 아침부터 72시간, 수·금요일은 직전 발행일부터 48시간
- 결과는 docs/rx/날짜/ 폴더에 저장 (매일 브리핑과 별도 목록)
- 네이버 검색·매체 목록·제외어·카드뉴스 디자인은 매일 브리핑 코드를 함께 씀

실행 전 환경변수: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, ANTHROPIC_API_KEY
"""

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta

import anthropic

import make_cardnews
from collect_and_summarize import EXCLUDE_TERMS, KST, MODEL, PRESS, search_news

# ─────────────────────────────────────────
# 설정 (필요하면 여기만 고치면 됨)
# ─────────────────────────────────────────
SERIES = "의료용 마약류 브리핑"
OUTPUT_DIR = os.path.join("docs", "rx")
MAX_ITEMS = 6           # 수·금
MONDAY_MAX_ITEMS = 8    # 월요일(주말 포함)

# 국내에서는 마약류가 아니지만 해외에서 마약류로 관리되는 약물 (추가·삭제 가능)
WATCH_DRUGS = ["트라마돌", "프레가발린", "가바펜틴", "티아넵틴", "덱스트로메토르판"]

KEYWORDS = [
    # 의료용 마약류
    "의료용 마약류", "향정신성의약품", "마약류 처방", "마약류통합관리시스템",
    "프로포폴", "졸피뎀", "옥시코돈", "펜타닐 패치", "메틸페니데이트", "ADHD 치료제",
    "식욕억제제", "펜터민", "디에타민", "벤조디아제핀", "알프라졸람", "수면제 오남용",
    "의료쇼핑", "셀프 처방", "마약류 오남용",
    # 국내 미지정·해외 통제 약물
    *WATCH_DRUGS, "코데인", "처방약 오남용",
    # 일반의약품 오남용·오버도즈
    "일반의약품 오남용", "오버도즈", "약물 과다복용", "청소년 오버도즈", "수면유도제",
    "수면유도제 과다복용", "감기약 과다복용", "기침약 오남용", "기침 시럽 오남용",
    "디펜히드라민", "독시라민", "진통제 과다복용", "아세트아미노펜 과다복용", "약물 중독 청소년",
]

# 매일 브리핑과 구분되는 색 (보라 계열)
THEME = {"#123C36": "#3A2E6B", "#DCEBE6": "#E6E1F5", "#E8A33D": "#E36F8F",
         "#94590A": "#A63D5C", "#F4F7F6": "#F6F5FA", "#C9D8D3": "#D6D1E6"}


# ─────────────────────────────────────────
# 1. 수집
# ─────────────────────────────────────────
def collect(hours: int) -> list:
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    by_url, seen = {}, set()
    for kw in KEYWORDS:
        for a in search_news(kw, cutoff):
            key = (a["press"], re.sub(r"\W", "", a["title"]))
            if a["url"] in by_url or key in seen:
                continue
            by_url[a["url"]] = a
            seen.add(key)
    arts = sorted(by_url.values(), key=lambda x: x["published"], reverse=True)
    arts = [a for a in arts if not any(t in a["title"] + a["description"] for t in EXCLUDE_TERMS)]
    counts = Counter(a["press"] for a in arts)
    print(f"\n[수집] 총 {len(arts)}건")
    for name in PRESS.values():
        print(f"  - {name}: {counts.get(name, 0)}건")
    return arts


# ─────────────────────────────────────────
# 2. 선정·요약 (Claude)
# ─────────────────────────────────────────
SYSTEM_PROMPT = """너는 경기도약사회 마약퇴치사업본부의 '의료용 마약류 브리핑'을 작성한다.
독자는 마약류 중독 예방교육과 치료·재활 지원 활동을 하는 사람들이다.
반드시 JSON만 출력하고, 설명이나 코드블록 표시(```)는 붙이지 않는다."""

USER_PROMPT = """아래는 {period} 수집한 기사 목록(제목·요약문)이다. 각 기사에는 번호(id)가 있다.

[대상 기사] 아래 두 가지에 해당하는 기사만 고른다.
A. 의료용 마약류: 병원·약국에서 처방되는 마약류·향정신성의약품(프로포폴, 졸피뎀, 옥시코돈·펜타닐 등 마약성 진통제,
   ADHD 치료제, 식욕억제제, 벤조디아제핀계 등)의 오남용·불법 처방·유통·과다복용, 관련 정책·제도·통계·연구
B. 국내 미지정·해외 통제 약물: 국내에서는 마약류로 지정되지 않았지만 해외에서는 마약류로 관리되는 약물의
   오남용·사고·규제 동향. 다음 약물이 해당한다: {watch}
   (이 목록 밖의 약물은 기사에 해외 통제 사실이 나와 있을 때만 B로 본다)
C. 일반의약품 오남용: 약국에서 처방 없이 살 수 있는 약(수면유도제, 감기약, 기침약·기침 시럽, 진통제 등)을
   과량 복용하는 오버도즈(OD), 의도적 오남용, 이로 인한 사고·응급실 이송, 실태조사·통계, 판매 규제 논의.
   특히 청소년 사이 유행·SNS 확산을 다룬 기사를 중시한다.
   단, 실수로 약을 잘못 먹은 단순 안전사고나 의약품 일반 정보 기사는 제외한다.

[제외할 기사]
- 필로폰·대마·코카인·엑스터시 등 불법 마약만 다룬 기사 (의료용 마약류가 함께 관련되면 포함)
- 기관·단체·지자체·기업의 캠페인, 행사, 교육, 기부, 업무협약(MOU), 수상 등 활동 소식과 홍보성 기사
- 코리아스타트업포럼(코스포) 등 비대면진료·의약품 배송 플랫폼 업계의 주장이나 입장을 전하는 기사
- 비유적 표현('마약김밥' 등)

[작성 규칙]
1. 같은 사안을 다룬 기사는 하나로 묶고, 그 기사들의 id를 모두 sources에 숫자로 넣는다.
2. 최대 {max_items}건을 고른다. 우선순위: 청소년 관련 사안 > 사건·사고(교육 사례로 쓸 만한 것) >
   새로운 정보(실태조사·통계·연구, 새로 유행하는 약물·수법, 해외 규제 변화) > 정책·제도.
   A·B·C가 한쪽으로 쏠리지 않게 하되, 대상 기사가 부족하면 적게 내도 되고, 억지로 채우지 않는다.
3. 분류는 "일반의약품 오남용", "국내 미지정 약물", "사건·사고", "실태·연구", "정책·제도", "기타" 중에서 고르고 이 순서로 나열한다.
   C에 해당하는 사안은 모두 "일반의약품 오남용", B에 해당하는 사안은 모두 "국내 미지정 약물"로 분류한다. 해당 기사가 없는 분류는 생략한다.
4. flag: C이면서 청소년 관련이면 "청소년 오버도즈", C이면 "일반의약품", B이면 "해외 통제 약물",
   그 밖에 청소년 관련이면 "청소년 관련", 해당 없으면 빈 문자열.
5. summary는 제공된 제목·요약문의 사실만 사용하고 추측하지 않는다. 2문장, 120자 이내로 새로 구성한다.
6. headline은 가장 중요한 이슈 한 문장(30자 이내).
7. daily_comment는 예방교육·치료재활 현장에 주는 메시지 2문장(120자 이내).
   오버도즈 기사를 다룰 때 복용량·약 조합·방법 같은 구체적 정보는 summary와 daily_comment 어디에도 쓰지 않는다. 기사에 없는 법 조항·수치·제도명을
   지어내지 않고, 약물의 국내 법적 지위도 기사나 위 목록에 근거가 있을 때만 언급한다.
8. 대상 기사가 하나도 없으면 categories를 빈 배열로 하고 headline에 그 사실을 쓴다.

[출력 형식]
{{
  "headline": "핵심 한 줄",
  "categories": [
    {{"name": "분류명", "items": [
      {{"title": "사안 제목(25자 이내)", "summary": "2문장 요약", "flag": "", "sources": [기사 id 숫자, ...]}}
    ]}}
  ],
  "daily_comment": "한마디",
  "excluded_count": 제외한_기사_수
}}

[기사 목록]
{articles}
"""


def summarize(articles: list, max_items: int, period: str) -> dict:
    if not articles:
        return {"headline": "이번 기간에는 의료용 마약류·의약품 오남용 관련 기사가 없습니다.",
                "categories": [], "daily_comment": "", "excluded_count": 0}
    payload = [{"id": i, "press": a["press"], "title": a["title"], "description": a["description"]}
               for i, a in enumerate(articles)]
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=8000, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_PROMPT.format(
            period=period, max_items=max_items, watch=", ".join(WATCH_DRUGS),
            articles=json.dumps(payload, ensure_ascii=False, indent=1))}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    result = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())

    # 기사 번호 → 원래 기사의 매체명·주소 (주소는 AI가 쓰지 않음)
    left = max_items
    for cat in result.get("categories", []):
        kept = []
        for item in cat.get("items", []):
            srcs, seen = [], set()
            for sid in item.get("sources", []):
                try:
                    a = articles[int(sid)]
                except (ValueError, TypeError, IndexError):
                    continue
                if a["url"] not in seen:
                    seen.add(a["url"])
                    srcs.append({"press": a["press"], "url": a["url"]})
            if srcs and left > 0:
                item["sources"] = srcs
                kept.append(item)
                left -= 1
        cat["items"] = kept
    result["categories"] = [c for c in result.get("categories", []) if c["items"]]
    return result


# ─────────────────────────────────────────
# 3. 저장
# ─────────────────────────────────────────
def to_text(s: dict) -> str:
    lines = [f"■ {SERIES} ({s['date']})", "", f"▶ {s['headline']}", ""]
    for cat in s.get("categories", []):
        lines.append(f"[{cat['name']}]")
        for it in cat["items"]:
            mark = f" ({it['flag']})" if it.get("flag") else ""
            lines.append(f"· {it['title']}{mark}")
            lines.append(f"  {it['summary']}")
            lines += [f"  {x['press']} {x['url']}" for x in it["sources"]]
        lines.append("")
    if s.get("daily_comment"):
        lines += [f"■ 한마디\n{s['daily_comment']}", ""]
    return "\n".join(lines)


def update_index():
    days = sorted((d for d in os.listdir(OUTPUT_DIR)
                   if d.isdigit() and os.path.exists(os.path.join(OUTPUT_DIR, d, "index.html"))), reverse=True)
    rows = "".join(f'<li><a href="{d}/">{d[:4]}.{d[4:6]}.{d[6:]}</a></li>' for d in days)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<meta name="robots" content="noindex"><title>{SERIES}</title>'
                '<style>body{font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 20px;'
                'line-height:1.8;font-size:20px}a{color:#3A2E6B}</style></head>'
                f'<body><h1>{SERIES}</h1><ul>{rows}</ul></body></html>')


def main():
    today = datetime.now(KST)
    if today.weekday() == 0:
        hours, max_items, label = 72, MONDAY_MAX_ITEMS, "금·토·일 소식"
        period = "지난 금요일 아침부터 오늘 아침까지(약 72시간)"
    else:
        hours, max_items, label = 48, MAX_ITEMS, "최근 이틀 소식"
        period = "최근 48시간 동안"
    print(f"[기간] 최근 {hours}시간, 최대 {max_items}건")

    summary = summarize(collect(hours), max_items, period)
    summary.update(date=today.strftime("%Y.%m.%d"), series=SERIES, period_label=label)

    day_dir = os.path.join(OUTPUT_DIR, today.strftime("%Y%m%d"))
    os.makedirs(day_dir, exist_ok=True)
    text = to_text(summary)
    with open(os.path.join(day_dir, "briefing.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)

    # 카드뉴스: 매일 브리핑 디자인을 쓰되 이름과 색만 바꿈
    make_cardnews.SERIES = SERIES
    for old, new in THEME.items():
        make_cardnews.CSS = make_cardnews.CSS.replace(old, new)
        make_cardnews.WEB_CSS = make_cardnews.WEB_CSS.replace(old, new)
    make_cardnews.render(summary, day_dir)

    with open(os.path.join(day_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    update_index()
    print(f"\n[저장] {day_dir}")


if __name__ == "__main__":
    main()
