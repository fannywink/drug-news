"""
카카오톡 전송 (3단계)

- 오늘 브리핑 웹페이지가 인터넷에 올라왔는지 확인한 뒤
- 카카오톡 "나에게 보내기"로 표지 이미지 + 헤드라인 + [카드뉴스·원문 보기] 버튼을 보냄

필요한 환경변수 (GitHub Secrets에 등록):
  KAKAO_REST_API_KEY    카카오 앱의 REST API 키
  KAKAO_REFRESH_TOKEN   kakao-token-setup 실행 시 자동 저장됨
  KAKAO_CLIENT_SECRET   (선택) 카카오 앱에서 Client Secret을 켠 경우만
  SITE_URL              GitHub Pages 주소 (예: https://아이디.github.io/저장소이름)
  GH_TOKEN              (선택) 리프레시 토큰 자동 갱신용 GitHub 토큰
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def save_new_refresh_token(token: str):
    """카카오가 새 리프레시 토큰을 주면(만료 1개월 전부터) GitHub Secret을 바꿔 둠"""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and os.environ.get("GH_TOKEN"):
        subprocess.run(["gh", "secret", "set", "KAKAO_REFRESH_TOKEN", "--body", token, "--repo", repo],
                       check=True)
        print("[카카오] 리프레시 토큰을 새로 받아 GitHub Secret을 갱신함")
    else:
        with open("kakao_refresh_token.txt", "w") as f:
            f.write(token)
        print("[카카오] 새 리프레시 토큰을 kakao_refresh_token.txt에 저장함 → Secret에 직접 바꿔 넣어야 함")


def get_access_token() -> str:
    data = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_API_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    if os.environ.get("KAKAO_CLIENT_SECRET"):
        data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
    r = requests.post(TOKEN_URL, data=data, timeout=10)
    if r.status_code != 200:
        sys.exit(f"[카카오] 토큰 갱신 실패: {r.text}\n→ Actions의 kakao-token-setup으로 토큰을 다시 발급받아야 할 수 있음")
    tok = r.json()
    if tok.get("refresh_token"):
        save_new_refresh_token(tok["refresh_token"])
    return tok["access_token"]


def wait_until_live(url: str, timeout: int = 600):
    """GitHub Pages 반영(보통 1~3분)을 기다림"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(url, timeout=10).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(15)
    return False


def main():
    today = datetime.now(KST)
    ymd = today.strftime("%Y%m%d")
    with open(os.path.join("docs", ymd, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)

    page_url = f"{os.environ['SITE_URL'].rstrip('/')}/{ymd}/"
    image_url = page_url + "card_01.png"
    if not wait_until_live(image_url):
        print("[경고] 페이지가 아직 열리지 않음. 그래도 전송함 (잠시 뒤 열림)")

    count = sum(len(c["items"]) for c in summary.get("categories", []))
    link = {"web_url": page_url, "mobile_web_url": page_url}
    template = {
        "object_type": "feed",
        "content": {
            "title": summary.get("headline", "마약류 뉴스 브리핑"),
            "description": f"{today.month}월 {today.day}일 마약류 주요 뉴스 {count}건과 원문 링크",
            "image_url": image_url,
            "image_width": 1080,
            "image_height": 1350,
            "link": link,
        },
        "buttons": [{"title": "카드뉴스·원문 보기", "link": link}],
    }

    r = requests.post(
        MEMO_URL,
        headers={"Authorization": f"Bearer {get_access_token()}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=10,
    )
    if r.status_code != 200 or r.json().get("result_code") != 0:
        sys.exit(f"[카카오] 전송 실패: {r.text}")
    print(f"[카카오] 전송 완료 → {page_url}")


if __name__ == "__main__":
    main()
