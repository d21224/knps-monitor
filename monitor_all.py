#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전체 국립공원 종합 모니터링
10분마다 모든 공원의 9월, 10월 주말 예약 체크
"""

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ComprehensiveParkMonitor:
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
        
        # 텔레그램 설정
        self.telegram_config = {
            'bot_token': '8474585269:AAGJdX-VYwffNBYImd3xAKGtZNEvDbfcy2M',
            'chat_id': '5428421984',
        }

    def setup_driver(self):
        """Chrome 드라이버 설정"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.implicitly_wait(10)
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
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except:
            return False

    def navigate_to_month(self, driver, target_month):
        """특정 월로 이동"""
        try:
            current_month_elem = driver.find_element(By.XPATH, "//*[contains(text(), '2025년')]")
            current_month_text = current_month_elem.text
            
            # 현재 월 파싱
            current_month = 9  # 기본값
            if "09월" in current_month_text:
                current_month = 9
            elif "08월" in current_month_text:
                current_month = 8
            elif "10월" in current_month_text:
                current_month = 10
            elif "11월" in current_month_text:
                current_month = 11
            
            clicks_needed = target_month - current_month
            
            if clicks_needed > 0:
                for i in range(clicks_needed):
                    next_btn = driver.find_element(By.CSS_SELECTOR, ".btn-next")
                    next_btn.click()
                    time.sleep(2)
            elif clicks_needed < 0:
                for i in range(-clicks_needed):
                    prev_btn = driver.find_element(By.CSS_SELECTOR, ".btn-prev")
                    prev_btn.click()
                    time.sleep(2)
            
            return True
            
        except Exception as e:
            logging.error(f"월 이동 실패: {e}")
            return False

    def parse_weekend_availability(self, page_text, month):
        """페이지 텍스트에서 주말 잔여석 정보 파싱"""
        available_dates = []
        
        try:
            pattern = r'(\d{1,2})\n([월화수목금토일])\n생활관 : 잔여 (\d+) 개'
            matches = re.findall(pattern, page_text)
            
            for day_str, weekday, remaining_str in matches:
                day = int(day_str)
                remaining = int(remaining_str)
                
                try:
                    date_obj = datetime(self.target_year, month, day)
                    weekday_num = date_obj.weekday()
                except ValueError:
                    continue
                
                # 주말이면서 잔여석이 1개 이상인 경우
                if weekday_num in self.weekend_days and remaining > 0:
                    weekday_name = "금요일" if weekday_num == 4 else "토요일"
                    available_dates.append({
                        'date': f"{self.target_year}-{month:02d}-{day:02d}",
                        'weekday': weekday_name,
                        'remaining': remaining
                    })
            
            return available_dates
            
        except Exception as e:
            logging.error(f"텍스트 파싱 실패: {e}")
            return []

    def check_park_availability(self, park_name):
        """특정 공원의 예약 가능 여부 체크"""
        driver = self.setup_driver()
        if not driver:
            return {}
            
        try:
            driver.get(self.url)
            time.sleep(8)
            
            # 공원 선택
            park_link = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{park_name}')]"))
            )
            park_link.click()
            time.sleep(3)
            
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
            driver.quit()

    def check_all_parks(self):
        """모든 공원 체크"""
        logging.info("=== 전체 국립공원 체크 시작 ===")
        
        all_results = {}
        
        for park_name in self.parks.keys():
            logging.info(f"🏔️ {park_name} 체크 중...")
            park_result = self.check_park_availability(park_name)
            
            if park_result:
                all_results[park_name] = park_result
                
            time.sleep(3)  # 공원 간 대기
        
        logging.info("=== 전체 국립공원 체크 완료 ===")
        return all_results

    def send_comprehensive_report(self, all_results):
        """종합 결과 보고서 발송"""
        if not all_results:
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
        
        if not available_parks:
            # 예약 가능한 곳이 없으면 간단한 상태 메시지
            message = f"""📊 <b>국립공원 예약 현황</b>

🕐 체크 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

❌ 현재 9월, 10월 주말에 예약 가능한 국립공원이 없습니다.

다음 체크: 10분 후"""
            
            return self.send_telegram_message(message)
        
        # 예약 가능한 곳이 있으면 상세 보고서
        message = f"""🎉 <b>국립공원 주말 예약 가능!</b>

🕐 체크 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

"""
        
        for park_name, months_data in available_parks.items():
            message += f"🏔️ <b>{park_name}</b>\n"
            
            for month_name, dates in months_data.items():
                if dates:
                    message += f"  📅 {month_name}: {len(dates)}개 주말 예약 가능\n"
                    for date_info in dates:
                        message += f"    • {date_info['date']} ({date_info['weekday']}) - 잔여 {date_info['remaining']}개\n"
                else:
                    message += f"  📅 {month_name}: 주말 예약 불가\n"
            message += "\n"
        
        message += f"""🔗 <b>예약 링크:</b>
{self.url}

⚡ <b>빠른 예약을 권장합니다!</b>
다음 체크: 10분 후"""
        
        return self.send_telegram_message(message)

    def run_continuous_monitoring(self):
        """연속 모니터링 실행 (10분마다)"""
        check_interval = 10 * 60  # 10분
        
        # 시작 알림
        start_message = f"""🚀 <b>국립공원 종합 모니터링 시작!</b>

🏔️ 대상: <b>전체 9개 국립공원</b>
📅 기간: <b>2025년 9월, 10월</b>
🗓️ 요일: <b>주말 (금요일, 토요일)</b>
⏰ 체크 간격: <b>10분</b>

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ 모니터링 시작됨!"""
        
        self.send_telegram_message(start_message)
        logging.info("전체 국립공원 연속 모니터링 시작...")
        
        check_count = 0
        while True:
            try:
                check_count += 1
                logging.info(f"🔄 {check_count}번째 전체 체크 시작...")
                
                all_results = self.check_all_parks()
                self.send_comprehensive_report(all_results)
                
                # 1시간마다 상태 알림 (6번 체크 = 1시간)
                if check_count % 6 == 0:
                    status_msg = f"🤖 전체 국립공원 모니터링 정상 작동 중...\n📊 {check_count}번째 체크 완료"
                    self.send_telegram_message(status_msg)
                
                logging.info(f"⏰ 다음 체크까지 {check_interval//60}분 대기...")
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                logging.info("⏹️ 모니터링 중단")
                self.send_telegram_message("⏹️ 국립공원 종합 모니터링 중단됨")
                break
            except Exception as e:
                logging.error(f"❌ 모니터링 오류: {e}")
                self.send_telegram_message(f"❌ 모니터링 오류 발생: {e}\n1분 후 재시도")
                time.sleep(60)

def main():
    monitor = ComprehensiveParkMonitor()
    
    print("🏔️ 국립공원 종합 모니터링")
    print("=" * 50)
    print("전체 9개 국립공원의 9월, 10월 주말 예약을 10분마다 체크합니다.")
    print()
    print("모니터링 대상:")
    for park_name in monitor.parks.keys():
        print(f"  • {park_name}")
    print()
    print("1. 한 번만 전체 체크")
    print("2. 연속 모니터링 (10분마다)")
    
    choice = input("선택하세요 (1 또는 2): ")
    
    if choice == "1":
        print("\n🔍 전체 국립공원 단일 체크 실행...")
        all_results = monitor.check_all_parks()
        monitor.send_comprehensive_report(all_results)
        print("✅ 단일 체크 완료!")
    elif choice == "2":
        print("\n🔄 전체 국립공원 연속 모니터링 시작...")
        monitor.run_continuous_monitoring()
    else:
        print("잘못된 선택입니다.")

if __name__ == "__main__":
    main()