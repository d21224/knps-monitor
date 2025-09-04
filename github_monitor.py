# .github/workflows/knps-monitor.yml
name: 국립공원 예약 모니터링 (상태 변화 감지)

on:
  schedule:
    # 10분마다 실행 (UTC 기준)
    - cron: '*/10 * * * *'
  workflow_dispatch: # 수동 실행도 가능

permissions:
  contents: write  # 상태 파일 커밋을 위해 필요

jobs:
  monitor:
    runs-on: ubuntu-latest
    
    steps:
    - name: 코드 체크아웃
      uses: actions/checkout@v4
      with:
        token: ${{ secrets.GITHUB_TOKEN }}
        
    - name: Python 설정
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
        
    - name: Chrome 브라우저 설치
      uses: browser-actions/setup-chrome@latest
      
    - name: ChromeDriver 설치
      uses: nanasess/setup-chromedriver@master
      
    - name: Python 의존성 설치
      run: |
        pip install selenium requests
        
    - name: Git 저장소 최신 상태로 업데이트
      run: |
        git pull origin main
        
    - name: 국립공원 예약 모니터링 실행
      env:
        TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
        TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      run: |
        python github_actions_monitor_with_state.py
        
    - name: 실행 로그 업로드 (실패시)
      if: failure()
      uses: actions/upload-artifact@v3
      with:
        name: monitoring-logs
        path: "*.log"
