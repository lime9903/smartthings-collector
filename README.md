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

# 3. config.json 설정
cp config.example.json config.json
# config.json 열어서 CLIENT_ID, CLIENT_SECRET 입력

# 4. 최초 인증 (1회만)
python smartthings_auth.py

# 5. 실행
python launcher.py
```

---

## config.json 설정 방법

1. [SmartThings Developer Console](https://developer.smartthings.com) 접속
2. 새 앱 생성 → OAuth 클라이언트 발급
3. `config.example.json`을 복사해서 `config.json` 생성 후 입력

```json
{
    "CLIENT_ID": "발급받은_CLIENT_ID",
    "CLIENT_SECRET": "발급받은_CLIENT_SECRET"
}
```

> ⚠️ `config.json`은 절대 GitHub에 올리지 마세요. `.gitignore`에 포함되어 있습니다.

---

## 파일 구조

```
smartthings-collector/
├── launcher.py
├── smartthings_collector.py
├── smartthings_dashboard.py
├── smartthings_auth.py
├── config.example.json         ← 이걸 복사해서 config.json 만들기
├── requirements.txt
├── build.bat
└── installer.iss
```

---

## 기기 별칭 설정

`smartthings_dashboard.py`의 `DEVICE_ALIAS` 딕셔너리를 수정하세요.

```python
DEVICE_ALIAS = {
    "SMP01": "내 PC",
    "SMP02": "프린터",
}
```

---

## License

MIT
