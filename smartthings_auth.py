"""
=== SmartThings 최초 인증 스크립트 ===
이 스크립트는 최초 1회만 실행하면 됩니다.
이후 토큰 갱신은 smartthings_collector.py가 자동으로 처리합니다.

실행 방법:
    python smartthings_auth.py

인증 순서:
    1. 브라우저가 열립니다.
    2. Samsung 계정으로 로그인 후 권한을 허용합니다.
    3. 브라우저가 https://httpbin.org/get?code=xxxx 페이지로 이동합니다.
    4. JSON에서 "code" 값을 복사해서 터미널에 붙여넣으세요.
    5. 자동으로 토큰을 발급받아 파일에 저장합니다.

필요한 라이브러리:
    pip install aiohttp
"""

import json
import os
import webbrowser
import secrets
import aiohttp
import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64

# =============================================
# 설정
# =============================================
CLIENT_ID     = "075a7bc0-263d-4343-b383-c855f9380654"
CLIENT_SECRET = "776977f3-99bb-4e3e-81c0-668800235b15"
REDIRECT_URI  = "https://httpbin.org/get"
SCOPES        = "r:devices:* w:devices:* x:devices:* r:hubs:* r:locations:* w:locations:* x:locations:* r:scenes:* x:scenes:* r:rules:* w:rules:* r:installedapps w:installedapps"

TOKEN_FILE = os.path.abspath("C:/smartthings_data/tokens/oauth_token.json")
os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)

AUTH_URL  = "https://api.smartthings.com/oauth/authorize"
TOKEN_URL = "https://api.smartthings.com/oauth/token"

STATE = secrets.token_hex(16)


def make_basic_auth_header(client_id, client_secret):
    """Basic Auth 헤더를 생성합니다. (curl -u 방식과 동일)"""
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


async def exchange_code_for_token(code: str) -> dict:
    """
    authorization code를 access_token + refresh_token으로 교환합니다.
    SmartThings는 Basic Auth 방식을 사용합니다.
    curl -X POST "https://api.smartthings.com/oauth/token"
         -u "clientId:clientSecret"
         -d "grant_type=authorization_code&code=xxx&redirect_uri=xxx"
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(
            TOKEN_URL,
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": REDIRECT_URI,
                "client_id":    CLIENT_ID,
            },
            headers={
                "Content-Type":  "application/x-www-form-urlencoded",
                "Authorization": make_basic_auth_header(CLIENT_ID, CLIENT_SECRET),
            }
        ) as resp:
            text = await resp.text()
            if resp.status == 200:
                return json.loads(text)
            else:
                raise Exception(f"토큰 교환 실패 ({resp.status}): {text}")


def save_token(token_data: dict):
    """토큰 데이터를 파일에 저장합니다."""
    expires_in = int(token_data.get("expires_in", 86400))
    token_data["expires_at"] = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=4)
    print(f"\n✅ 토큰이 저장되었습니다: {TOKEN_FILE}")


def main():
    params = urlencode({
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "state":         STATE,
    })
    auth_url = f"{AUTH_URL}?{params}"

    print("=" * 60)
    print("SmartThings OAuth 최초 인증을 시작합니다.")
    print("=" * 60)
    print("\n[1단계] 브라우저에서 Samsung 계정으로 로그인 후 권한을 허용해주세요.")
    print("\n브라우저가 자동으로 열리지 않으면 아래 URL을 직접 열어주세요:")
    print(f"\n{auth_url}\n")

    webbrowser.open(auth_url)

    print("-" * 60)
    print("[2단계] 권한 허용 후 브라우저가 아래 페이지로 이동합니다:")
    print("  https://httpbin.org/get?code=XXXXXX&state=XXXXXX")
    print('\n페이지의 JSON에서 "code" 값을 복사하세요.')
    print('예시:  "code": "820gPa"  →  820gPa  를 복사')
    print("-" * 60)

    code = input("\n▶ code 값을 여기에 붙여넣으세요: ").strip()

    if not code:
        print("❌ code가 입력되지 않았습니다. 다시 실행해주세요.")
        return

    print("\nAccess token으로 교환 중...")

    try:
        token_data = asyncio.run(exchange_code_for_token(code))
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        return

    save_token(token_data)

    print("\n=== 발급된 토큰 정보 ===")
    print(f"  access_token  : {str(token_data.get('access_token', ''))[:20]}...")
    print(f"  refresh_token : {str(token_data.get('refresh_token', ''))[:20]}...")
    print(f"  expires_in    : {token_data.get('expires_in')}초 (24시간)")
    print(f"  scope         : {token_data.get('scope')}")
    print(f"  만료 시각      : {token_data.get('expires_at')}")
    print("\n✅ 완료! 이제 smartthings_collector.py 를 실행하면 됩니다.")
    print("=" * 60)


if __name__ == "__main__":
    main()
