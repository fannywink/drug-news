"""
카카오 토큰 최초 발급 (GitHub Actions의 '카카오 토큰 발급' 버튼으로 실행됨)
- 브라우저에서 받은 인가 코드를 토큰으로 바꾸고, GitHub Secret KAKAO_REFRESH_TOKEN에 바로 저장함
- 토큰 값은 화면(로그)에 출력하지 않음
"""
import os
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

import requests

REDIRECT_URI = "https://localhost:3000"  # 카카오 앱에 등록한 Redirect URI와 같아야 함

raw = os.environ["KAKAO_CODE"].strip()
code = parse_qs(urlparse(raw).query).get("code", [raw])[0]  # 주소 전체를 붙여 넣어도 code만 추출

data = {"grant_type": "authorization_code", "client_id": os.environ["KAKAO_REST_API_KEY"],
        "redirect_uri": REDIRECT_URI, "code": code}
if os.environ.get("KAKAO_CLIENT_SECRET"):
    data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]

tok = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=10).json()
if "refresh_token" not in tok:
    sys.exit(f"발급 실패: {tok.get('error_description', tok)}\n"
             "→ 인가 코드는 한 번만, 몇 분 안에만 쓸 수 있음. 로그인 주소부터 다시 진행할 것")

subprocess.run(["gh", "secret", "set", "KAKAO_REFRESH_TOKEN", "--body", tok["refresh_token"],
                "--repo", os.environ["GITHUB_REPOSITORY"]], check=True)
print("성공: KAKAO_REFRESH_TOKEN을 저장함")
