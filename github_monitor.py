#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions용 국립공원 예약 모니터링
환경변수에서 텔레그램 정보를 가져와서 한 번 실행
"""

import os
import sys
import time
import logging
import requests
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# GitHub Actions 환경에 맞는 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

class GitHubActionsMonitor:
    def __init__(self):
        self.url = "https://reservation.knps.or.kr/eco/searchEcoMonthReservation.do"
        self.target_year = 2025
        self.target_months = [9, 10]  # 9월, 10월
        self.weekend_days = [4, 5]  # 금요일(4), 토요일(5)
        
        # 모든 국립공원
        self.parks = {
            '북한산': 'B971002',
            '지리산': 'B014003',
            '소백산': 'B123002',
            '설악산': 'B301002',
            '한려해상': 'B024002',
            '무등산': 'B061002',
            '가야산': 'B051001',
            '내장산': 'B063002',
            '변산반도': 'B183001'
        }
        
        # 환경변수에서 텔레그램 정보 가져오기
        self.telegram_config = {
            'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
            'chat_id': os.environ.get('TELEGRAM_CHAT_ID'),
        }
        
        # 텔레그램 설정 확인
        if not self.telegram_config['bot_token'] or not self.telegram_config['chat_id']:
            logging.error("텔레그램 설정이 없습니다. GitHub Secrets를 확인하세요.")
            logging.error("TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID가 필요합니다.")
            sys.exit(1)

    def setup_driver(self):
        """GitHub Actions용 Chrome 드라이버 설정"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--remote-debugging-port=9222')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--allow-running-insecure-content')
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.implicitly_wait(15)  # GitHub Actions에서는 좀 더 여유있게
            return driver
        except Exception as e:
            logging.error(f"드라이버 설정 실패: {e}")
            return None

    def send_telegram_message(self, message):
        """텔레그램 메시지 발송"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_config['bot_token']}/sendMessage"
            data = {
                'chat_id': self.telegram_config['chat_id'],
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 200:
                logging.info("텔레그램 알림 발송 성공")
                return True
            else:
                logging.error(f"텔레그램 발송 실패: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"텔레그램 오류: {e}")
            return False

    def navigate_to_month(self, driver, target_month):
        """특정 월로 이동"""
        try:
            # 현재 월 파악
            month_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '월')]")
            current_month = 9  # 기본값
            
            for elem in month_elements:
                text = elem.text
                if "09월" in text:
                    current_month = 9
                    break
                elif "10월" in text:
                    current_month = 10
                    break
                elif "08월" in text:
                    current_month = 8
                    break
                elif "11월" in text:
                    current_month = 11
                    break
            
            logging.info(f"현재 월: {current_month}월, 목표 월: {target_month}월")
            
            clicks_needed = target_month - current_month
            
            if clicks_needed > 0:
                for i in range(clicks_needed):
                    next_btn = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-next"))
                    )
                    next_btn.click()
                    time.sleep(3)  # GitHub Actions에서는 더 여유있게
                    logging.info(f"다음 월로 이동 {i+1}/{clicks_needed}")
            elif clicks_needed < 0:
                for i in range(-clicks_needed):
                    prev_btn = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-prev"))
                    )
                    prev_btn.click()
                    time.sleep(3)
                    logging.info(f"이전 월로 이동 {i+1}/{-clicks_needed}")
            
            return True
            
        except Exception as e:
            logging.error(f"월 이동 실패: {e}")
            return False

    def parse_weekend_availability(self, page_text, month):
        """날짜와 잔여석 정보를 정확히 매칭하는 파싱 함수"""
        available_dates = []
        
        try:
            lines = page_text.split('\n')
            
            # 날짜와 잔여석 정보를 정확히 매칭
            for i, line in enumerate(lines):
                if re.match(r'^\d{1,2}$', line.strip()):
                    day = int(line.strip())
                    
                    # 해당 날짜의 잔여석 정보 찾기
                    remaining = None
                    for j in range(i+1, min(len(lines), i+10)):
                        remaining_match = re.search(r'생활관\s*:\s*잔여\s*(\d+)\s*개', lines[j])
                        if remaining_match:
                            remaining = int(remaining_match.group(1))
                            break
                    
                    # 잔여석 정보가 있는 경우만 처리
                    if remaining is not None:
                        try:
                            date_obj = datetime(self.target_year, month, day)
                            weekday_num = date_obj.weekday()
                            
                            # 주말이고 잔여석이 1개 이상인 경우
                            if weekday_num in self.weekend_days and remaining > 0:
                                weekday_name = "금요일" if weekday_num == 4 else "토요일"
                                available_dates.append({
                                    'date': f"{self.target_year}-{month:02d}-{day:02d}",
                                    'weekday': weekday_name,
                                    'remaining': remaining
                                })
                                logging.info(f"주말 예약 가능: {date_obj.strftime('%Y-%m-%d')} ({weekday_name}) - 잔여 {remaining}개")
                        
                        except ValueError:
                            continue
            
            logging.info(f"{month}월 주말 예약 가능: {len(available_dates)}개")
            return available_dates
            
        except Exception as e:
            logging.error(f"파싱 실패: {e}")
            return []

    def check_park_availability(self, park_name):
        """특정 공원의 예약 가능 여부 체크"""
        driver = self.setup_driver()
        if not driver:
            return {}
            
        try:
            logging.info(f"사이트 접속: {self.url}")
            driver.get(self.url)
            time.sleep(10)  # 충분한 로딩 시간
            
            # 공원 선택
            logging.info(f"{park_name} 선택 중...")
            park_link = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{park_name}')]"))
            )
            park_link.click()
            time.sleep(5)
            
            result = {}
            
            # 9월, 10월 각각 체크
            for month in self.target_months:
                if not self.navigate_to_month(driver, month):
                    continue
                    
                page_text = driver.find_element(By.TAG_NAME, "body").text
                available_dates = self.parse_weekend_availability(page_text, month)
                
                month_name = f"{month}월"
                result[month_name] = available_dates
                
                if available_dates:
                    logging.info(f"{park_name} {month_name}: {len(available_dates)}개 주말 예약 가능")
                else:
                    logging.info(f"{park_name} {month_name}: 주말 예약 불가")
            
            return result
            
        except Exception as e:
            logging.error(f"{park_name} 체크 실패: {e}")
            return {}
            
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    def check_all_parks(self):
        """모든 공원 체크"""
        logging.info("=== 전체 국립공원 체크 시작 ===")
        
        all_results = {}
        
        for park_name in self.parks.keys():
            logging.info(f"🏔️ {park_name} 체크 중...")
            park_result = self.check_park_availability(park_name)
            
            if park_result:
                all_results[park_name] = park_result
                
            time.sleep(5)  # 공원 간 대기
        
        logging.info("=== 전체 국립공원 체크 완료 ===")
        return all_results

    def send_comprehensive_report(self, all_results):
        """종합 결과 보고서 발송 - 예약 가능할 때만 발송"""
        if not all_results:
            logging.info("체크 결과가 없습니다")
            return False
            
        # 예약 가능한 공원들만 필터링
        available_parks = {}
        for park_name, months_data in all_results.items():
            park_has_availability = False
            for month_name, dates in months_data.items():
                if dates:
                    park_has_availability = True
                    break
            
            if park_has_availability:
                available_parks[park_name] = months_data
        
        # 예약 가능한 곳이 없으면 메시지 발송하지 않음
        if not available_parks:
            logging.info("예약 가능한 공원이 없어 알림 발송하지 않음")
            return False
        
        # 예약 가능한 곳이 있을 때만 알림 발송
        message = f"""🎉 국립공원 주말 예약 가능!

🕐 체크 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)

"""
        
        for park_name, months_data in available_parks.items():
            message += f"🏔️ {park_name}\n"
            
            for month_name, dates in months_data.items():
                if dates:
                    message += f"  📅 {month_name}: {len(dates)}개 주말 예약 가능\n"
                    for date_info in dates:
                        message += f"    • {date_info['date']} ({date_info['weekday']}) - 잔여 {date_info['remaining']}개\n"
            message += "\n"
        
        message += f"""🔗 예약 링크:
{self.url}

⚡ 빠른 예약을 권장합니다!

🤖 GitHub Actions 자동 모니터링"""
        
        return self.send_telegram_message(message)

    def run_single_check(self):
        """한 번의 체크 실행 (GitHub Actions용)"""
        logging.info("GitHub Actions에서 국립공원 예약 체크 시작")
        
        try:
            all_results = self.check_all_parks()
            success = self.send_comprehensive_report(all_results)
            
            if success:
                logging.info("예약 가능한 공원 발견 및 알림 발송 완료")
            else:
                logging.info("예약 가능한 공원이 없어 조용히 완료")
                
            return True
            
        except Exception as e:
            logging.error(f"체크 중 오류: {e}")
            # 오류 발생 시에도 텔레그램으로 알림
            error_message = f"❌ GitHub Actions 모니터링 오류 발생\n\n오류: {str(e)}\n\n시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)"
            self.send_telegram_message(error_message)
            return False

def main():
    """메인 실행 함수"""
    logging.info("GitHub Actions 국립공원 예약 모니터링 시작")
    
    monitor = GitHubActionsMonitor()
    
    success = monitor.run_single_check()
    
    if success:
        logging.info("모니터링 성공적으로 완료")
        sys.exit(0)
    else:
        logging.error("모니터링 실패")
        sys.exit(1)

if __name__ == "__main__":
    main()
