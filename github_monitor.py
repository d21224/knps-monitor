#!/usr/bin/env python3
import os
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

logging.basicConfig(level=logging.INFO)

class GitHubActionsMonitor:
    def __init__(self):
        self.url = "https://reservation.knps.or.kr/eco/searchEcoMonthReservation.do"
        self.target_year = 2025
        self.target_months = [9, 10]
        self.weekend_days = [4, 5]
        
        self.telegram_config = {
            'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
            'chat_id': os.environ.get('TELEGRAM_CHAT_ID'),
        }
        
        if not self.telegram_config['bot_token'] or not self.telegram_config['chat_id']:
            raise ValueError("텔레그램 환경변수가 설정되지 않았습니다")
        
        self.priority_parks = ['변산반도', '지리산', '설악산']

    def setup_driver(self):
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
        try:
            url = f"https://api.telegram.org/bot{self.telegram_config['bot_token']}/sendMessage"
            data = {
                'chat_id': self.telegram_config['chat_id'],
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=30)
            return response.status_code == 200
        except Exception as e:
            logging.error(f"텔레그램 발송 실패: {e}")
            return False

    def check_park_quick(self, park_name):
        driver = self.setup_driver()
        if not driver:
            return None
            
        try:
            driver.get(self.url)
            time.sleep(5)
            
            park_link = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{park_name}')]"))
            )
            park_link.click()
            time.sleep(2)
            
            available_weekends = []
            
            for month in self.target_months:
                if month == 10:
                    try:
                        next_btn = driver.find_element(By.CSS_SELECTOR, ".btn-next")
                        next_btn.click()
                        time.sleep(2)
                    except:
                        pass
                
                page_text = driver.find_element(By.TAG_NAME, "body").text
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
                    
                    if weekday_num in self.weekend_days and remaining > 0:
                        weekday_name = "금요일" if weekday_num == 4 else "토요일"
                        available_weekends.append({
                            'date': f"{self.target_year}-{month:02d}-{day:02d}",
                            'weekday': weekday_name,
                            'remaining': remaining
                        })
            
            return available_weekends
            
        except Exception as e:
            logging.error(f"{park_name} 체크 실패: {e}")
            return None
            
        finally:
            driver.quit()

    def run_single_check(self):
        logging.info("GitHub Actions 모니터링 시작...")
        
        all_available = {}
        
        for park_name in self.priority_parks:
            logging.info(f"{park_name} 체크 중...")
            result = self.check_park_quick(park_name)
            
            if result:
                all_available[park_name] = result
                logging.info(f"{park_name}: {len(result)}개 주말 예약 가능")
        
        if all_available:
            message = f"🏞️ 국립공원 주말 예약 가능!\n\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            for park_name, dates in all_available.items():
                message += f"🏔️ {park_name} ({len(dates)}개)\n"
                for date_info in dates:
                    message += f"  • {date_info['date']} ({date_info['weekday']}) - 잔여 {date_info['remaining']}개\n"
                message += "\n"
            
            self.send_telegram_message(message)

def main():
    try:
        monitor = GitHubActionsMonitor()
        monitor.run_single_check()
        print("✅ 모니터링 완료")
    except Exception as e:
        print(f"❌ 모니터링 실패: {e}")

if __name__ == "__main__":
    main()
