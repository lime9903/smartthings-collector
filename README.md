# SmartThings 데이터 수집기

SmartThings 스마트 플러그의 전력/에너지 데이터를 자동 수집하고 데스크탑 앱으로 실시간 모니터링하는 도구입니다.

---

## 주요 기능

- **자동 수집**: 60초마다 모든 기기의 전력(W), 에너지(Wh) 데이터 수집
- **CSV 저장**: 날짜별 폴더로 자동 분류 저장
- **데스크탑 대시보드**: 실시간 수집 현황, 기기별 상태 확인
- **그래프**: 기기 더블클릭 → 전력 사용량 그래프 (오늘/3일/7일)
- **토큰 자동 갱신**: 24시간마다 자동 갱신, 수동 불필요

---

## 설치 및 실행

### 방법 A — 설치 파일로 바로 실행 (권장)

1. [Releases](../../releases) 페이지에서 `SmartThingsCollector_Setup.exe` 다운로드
2. 설치 후 실행
3. 최초 1회 Samsung 계정 인증 → 이후 자동 실행

### 방법 B — Python으로 직접 실행 (개발자용)

```bash
# 1. 저장소 클론
git clone https://github.com/YOUR_USERNAME/smartthings-collector.git
cd smartthings-collector

# 2. 라이브러리 설치
pip install -r requirements.txt

# 3. SmartThings CLI 설치 및 OAuth 설정 (아래 참조)

# 4. 최초 인증 (1회만)
python smartthings_auth.py

# 5. 실행
python launcher.py
```

---

## SmartThings CLI로 OAuth Client 생성하기

웹 브라우저 없이 CLI로 OAuth Client ID와 Secret을 발급받는 방법입니다.

### 1단계: SmartThings CLI 설치

#### 📦 공식 GitHub 저장소
- **GitHub**: https://github.com/SmartThingsCommunity/smartthings-cli
- **공식 문서**: https://github.com/SmartThingsCommunity/smartthings-cli/blob/master/packages/cli/README.md
- **NPM 패키지**: https://www.npmjs.com/package/@smartthings/cli

#### Windows

```cmd
# Node.js 설치 확인 (없으면 https://nodejs.org 에서 설치)
node --version
npm --version

# SmartThings CLI 설치
npm install -g @smartthings/cli

# 설치 확인
smartthings --version
```

#### Linux (Ubuntu/Debian)

```bash
# Node.js 20.x LTS 설치
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# SmartThings CLI 설치
sudo npm install -g @smartthings/cli

# 설치 확인
smartthings --version
```

#### Linux (CentOS/RHEL/Fedora)

```bash
# Node.js 설치
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install -y nodejs

# SmartThings CLI 설치
sudo npm install -g @smartthings/cli
```

#### macOS

```bash
# Homebrew로 Node.js 설치
brew install node

# SmartThings CLI 설치
npm install -g @smartthings/cli
```

---

### 2단계: Samsung 계정으로 로그인

```bash
smartthings login
```

브라우저가 자동으로 열리고 Samsung 계정 로그인 → 권한 승인

**헤드리스 서버 환경 (브라우저 없음):**
```bash
smartthings login --no-browser
```
표시된 URL을 로컬 PC 브라우저에서 열고 인증 → 코드 복사 → 터미널에 붙여넣기

---

### 3단계: OAuth App 생성

```bash
smartthings apps:create
```

**입력 예시:**
```
? What kind of app do you want to create?: OAuth-In App
? Display Name: SmartThings Data Collector
? Description: Power monitoring data collector
? Icon Image URL (optional): [Press Enter]
? Target URL (optional): [Press Enter]
? Select Scopes: [Press <a>]
? Add or edit Redirect URIs: Add Redicrect URI
? Redirect URIs: https://httpbin.org/get
? Add or edit Redirect URIs: Finish editing Redirect URIs
? Choose an action: Finish and create OAuth-In SmartApp
```

**중요 설정:**
- **Redirect URIs**: 반드시 `https://httpbin.org/get` 입력 (코드의 REDIRECT_URI와 일치해야 함)
- **Scopes**: scope은 임의로 접근하고 싶은 항목만 설정 가능함

---

### 4단계: OAuth Client ID와 Secret 확인

설정이 완료되면 생성된 OAuth-In SmartApp의 정보와 OAuth Client Id와 OAuth Client Secret을 확인할 수 있습니다.
해당 값을 따로 저장해두시기 바랍니다.

**출력 예시:**
```
Basic App Data:
──────────────────────────────────────────────────────────
 Display Name     SmartThings Data Collector
 App Id           0f723e54-e8cd-40b1-a722-2c78fa35598c
 App Name         dc-6584b3fe-b0e3-411b-b740-acdc8a46434a
 Description      Power monitoring data collector
 Single Instance  true
 Classifications  CONNECTED_SERVICE
 App Type         API_ONLY
──────────────────────────────────────────────────────────


OAuth Info (you will not be able to see the OAuth info again so please save it now!):
──────────────────────────────────────────────────────────
OAuth Client Id:     075a7bc0-263d-4343-b383-c855f9380654
OAuth Client Secret: 776977f3-99bb-4e3e-81c0-668800235b15
──────────────────────────────────────────────────────────

```

⚠️ **Client Secret은 이 화면에서만 확인 가능합니다. 반드시 복사해두세요!**

---

### 5단계: config.json에 입력

프로젝트 디렉토리에 `config.json` 파일 수정:

```json
{
    "CLIENT_ID": "075a7bc0-263d-4343-b383-c855f9380654",
    "CLIENT_SECRET": "776977f3-99bb-4e3e-81c0-668800235b15"
}
```

---

### 6단계: Python 파일 실행

최초 인증을 위해 다음의 Python 파일을 실행합니다.
자동적으로 열리는 브라우저를 통해 인증을 수행하고 출력된 JSON 파일에서의 code 값을 복사하여 붙여놓습니다.

```bash
python smartthings_auth.py
```

그 다음, 데이터 수집 파일을 실행합니다.

```bash
python launcher.py
```


## 파일 구조

```
smartthings-collector/
├── launcher.py                 # 메인 런처
├── smartthings_collector.py    # 데이터 수집 백엔드
├── smartthings_dashboard.py    # tkinter 대시보드 UI
├── smartthings_auth.py         # OAuth 최초 인증 스크립트
├── config.json                 # OAuth Client ID/Secret (생성 필요)
├── requirements.txt            # Python 의존성
├── build.bat                   # Windows 빌드 스크립트
├── installer.iss               # Inno Setup 설치 파일
├── .gitignore                  # Git 무시 파일
└── README.md                   # 이 파일
```

---

## 기기 별칭 설정

`smartthings_dashboard.py`의 `DEVICE_ALIAS` 딕셔너리를 수정하세요.

```python
DEVICE_ALIAS = {
    "SMP01": "내 PC",
    "SMP02": "프린터",
    "SMP03": "냉장고",
}
```

---

## 문제 해결

### CLI 설치 오류

**권한 문제 (Linux):**
```bash
# npm 글로벌 설치 권한 문제 시
mkdir ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc

# 그 다음 재설치
npm install -g @smartthings/cli
```

**Windows PATH 문제:**
```cmd
# npm 글로벌 경로 확인
npm config get prefix

# PATH에 추가 (예시)
setx PATH "%PATH%;C:\Users\USERNAME\AppData\Roaming\npm"
```

### OAuth 인증 실패

1. **Redirect URI 불일치**: `https://httpbin.org/get`로 정확히 설정했는지 확인
2. **Client Secret 오타**: 공백 없이 정확히 복사했는지 확인
3. **앱 권한 부족**: 앱 생성 시 필요한 Scopes가 모두 선택되었는지 확인

### 토큰 갱신 실패

```bash
# 기존 토큰 파일 삭제 후 재인증
rm C:/smartthings_data/tokens/oauth_token.json  # Windows
rm /path/to/smartthings_data/tokens/oauth_token.json  # Linux

python smartthings_auth.py
```

---

## License

MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
