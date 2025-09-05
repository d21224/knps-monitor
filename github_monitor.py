#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions용 국립공원 예약 모니터링 - 상태 변화시만 알림
"""

import os
import sys
import json
import time
import logging
import requests
import re
import subprocess
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

class GitHubActionsMonitor:
    def __init__(self):
        self.url = "https://reservation.knps.or.kr/eco/searchEcoMonthReservation.do"
        self.target_year = 2025
        self.target_months = [9, 10]
        self.weekend_days = [4, 5]
        
        self.parks = {
            '북한산': 'B971002', '지리산': 'B014003', '소백산': 'B123002',
            '설악산': 'B301002', '한려해상': 'B024002', '무등산': 'B061002',
            '가야산': 'B051001', '내장산': 'B063002', '변산반도': 'B183001'
        }
        
        self.telegram_config = {
            'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
            'chat_id': os.environ.get('TELEGRAM_CHAT_ID'),
        }
        
        if not self.telegram_config['bot_token'] or not self.telegram_config['chat_id']:
            logging.error("텔레그램 설정이 없습니다. GitHub Secrets를 확인하세요.")
            sys.exit(1)
        
        self.state_file = 'knps_state.json'

    def load_previous_state(self):
        """이전 상태 로드"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                logging.info(f"이전 상태 로드됨: {len(state)} 항목")
                return state
            else:
                logging.info("첫 실행 - 이전 상태 없음")
                return {}
        except Exception as e:
            logging.error(f"상태 파일 로드 실패: {e}")
            return {}

    def save_current_state(self, current_results):
        """현재 상태를 Git에 저장"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(current_results, f, ensure_ascii=False, indent=2)
            
            subprocess.run(['git', 'config', 'user.name', 'KNPS Monitor'], check=True)
            subprocess.run(['git', 'config', 'user.email', 'knps-monitor@github-actions'], check=True)
            
            subprocess.run(['git', 'add', self.state_file], check=True)
            
            try:
                subprocess.run(['git', 'commit', '-m', f'Update monitoring state - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'], 
                              check=True, capture_output=True, text=True)
                logging.info("상태 파일 커밋 완료")
            except subprocess.CalledProcessError as e:
                if "nothing to commit" in str(e.stdout):
                    logging.info("상태 변화 없어 커밋하지 않음")
                else:
                    logging.error(f"커밋 실패: {e}")
            
            try:
                subprocess.run(['git', 'push'], check=True, capture_output=True)
                logging.info("상태 파일 푸시 완료")
            except subprocess.CalledProcessError as e:
                logging.error(f"푸시 실패: {e}")
                
        except Exception as e:
            logging.error(f"상태 저장 실패: {e}")

    def compare_states(self, previous_state, current_results):
        """상태 비교"""
        changes = {'new': {}, 'removed': {}, 'updated': {}}
        
        try:
            current_flat = {}
            for park_name, months_data in current_results.items():
                for month_name, dates in months_data.items():
                    for date_info in dates:
                        key = f"{park_name}-{date_info['date']}"
                        current_flat[key] = {
                            'park': park_name, 'month': month_name,
                            'date': date_info['date'], 'weekday': date_info['weekday'],
                            'remaining': date_info['remaining']
                        }
            
            previous_flat = {}
            for park_name, months_data in previous_state.items():
                for month_name, dates in months_data.items():
                    for date_info in dates:
                        key = f"{park_name}-{date_info['date']}"
                        previous_flat[key] = {
                            'park': park_name, 'month': month_name,
                            'date': date_info['date'], 'weekday': date_info['weekday'],
                            'remaining': date_info['remaining']
                        }
            
            # 새로 생긴 예약
            for key, data in current_flat.items():
                if key not in previous_flat:
                    park = data['park']
                    if park not in changes['new']:
                        changes['new'][park] = []
                    changes['new'][park].append(data)
                elif previous_flat[key]['remaining'] != data['remaining']:
                    park = data['park']
                    if park not in changes['updated']:
                        changes['updated'][park] = []
                    changes['updated'][park].append({
                        **data,
                        'prev_remaining': previous_flat[key]['remaining'],
                        'curr_remaining': data['remaining']
                    })
            
            # 사라진 예약
            for key, data in previous_flat.items():
                if key not in current_flat:
                    park = data['park']
                    if park not in changes['removed']:
                        changes['removed'][park] = []
                    changes['removed'][park].append(data)
            
            return changes
            
        except Exception as e:
            logging.error(f"상태 비교 실패: {e}")
            return changes

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
            driver.implicitly_wait(15)
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
            return response.status_code == 200
        except Exception as e:
            logging.error(f"텔레그램 오류: {e}")
            return False

    def navigate_to_month(self, driver, target_month):
        """월 이동"""
        try:
            month_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '월')]")
            current_month = 9
            
            for elem in month_elements:
                text = elem.text
                if "09월" in text:
                    current_month = 9
                    break
                elif "10월" in text:
                    current_month = 10
                    break
            
            clicks_needed = target_month - current_month
            
            if clicks_needed > 0:
                for i in range(clicks_needed):
                    next_btn = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-next"))
                    )
                    next_btn.click()
                    time.sleep(3)
            elif clicks_needed < 0:
                for i in range(-clicks_needed):
                    prev_btn = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-prev"))
                    )
                    prev_btn.click()
                    time.sleep(3)
            
            return True
        except Exception as e:
            logging.error(f"월 이동 실패: {e}")
            return False

    def parse_weekend_availability(self, page_text, month):
        """주말 예약 파싱"""
        available_dates = []
        
        try:
            lines = page_text.split('\n')
            
            for i, line in enumerate(lines):
                if re.match(r'^\d{1,2}$', line.strip()):
                    day = int(line.strip())
                    
                    remaining = None
                    for j in range(i+1, min(len(lines), i+10)):
                        remaining_match = re.search(r'생활관\s*:\s*잔여\s*(\d+)\s*개', lines[j])
                        if remaining_match:
                            remaining = int(remaining_match.group(1))
                            break
                    
                    if remaining is not None:
                        try:
                            date_obj = datetime(self.target_year, month, day)
                            weekday_num = date_obj.weekday()
                            
                            if weekday_num in self.weekend_days and remaining > 0:
                                weekday_name = "금요일" if weekday_num == 4 else "토요일"
                                available_dates.append({
                                    'date': f"{self.target_year}-{month:02d}-{day:02d}",
                                    'weekday': weekday_name,
                                    'remaining': remaining
                                })
                        except ValueError:
                            continue
            
            return available_dates
        except Exception as e:
            logging.error(f"파싱 실패: {e}")
            return []

    def check_park_availability(self, park_name):
        """공원 체크"""
        driver = self.setup_driver()
        if not driver:
            return {}
            
        try:
            driver.get(self.url)
            time.sleep(10)
            
            park_link = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{park_name}')]"))
            )
            park_link.click()
            time.sleep(5)
            
            result = {}
            
            for month in self.target_months:
                if not self.navigate_to_month(driver, month):
                    continue
                    
                page_text = driver.find_element(By.TAG_NAME, "body").text
                available_dates = self.parse_weekend_availability(page_text, month)
                
                month_name = f"{month}월"
                result[month_name] = available_dates
            
            return result
        except Exception as e:
            logging.error(f"{park_name} 체크 실패: {e}")
            return {}
        finally:
            if driver:
                driver.quit()

    def check_all_parks(self):
        """모든 공원 체크"""
        all_results = {}
        
        for park_name in self.parks.keys():
            logging.info(f"{park_name} 체크 중...")
            park_result = self.check_park_availability(park_name)
            
            if park_result:
                all_results[park_name] = park_result
            time.sleep(5)
        
        return all_results

    def send_change_notification(self, changes):
        """변화 알림"""
        if not any(changes.values()):
            return False
            
        message = f"""🔄 국립공원 예약 상태 변화!

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)

"""
        
        if changes['new']:
            message += "🆕 새로 예약 가능:\n"
            for park_name, dates in changes['new'].items():
                message += f"🏔️ {park_name}\n"
                for date_info in dates:
                    message += f"  • {date_info['date']} ({date_info['weekday']}) - 잔여 {date_info['remaining']}개\n"
            message += "\n"
        
        if changes['removed']:
            message += "❌ 예약 불가능해짐:\n"
            for park_name, dates in changes['removed'].items():
                message += f"🏔️ {park_name}\n"
                for date_info in dates:
                    message += f"  • {date_info['date']} ({date_info['weekday']})\n"
            message += "\n"
        
        if changes['updated']:
            message += "📊 잔여석 수량 변화:\n"
            for park_name, dates in changes['updated'].items():
                message += f"🏔️ {park_name}\n"
                for date_info in dates:
                    message += f"  • {date_info['date']} ({date_info['weekday']}) {date_info['prev_remaining']}개 → {date_info['curr_remaining']}개\n"
            message += "\n"
        
        message += f"🔗 {self.url}\n\n🤖 GitHub Actions 자동 모니터링"
        
        return self.send_telegram_message(message)

    def run_single_check(self):
        """한 번의 체크 실행"""
        logging.info("GitHub Actions 모니터링 시작")
        
        try:
            previous_state = self.load_previous_state()
            current_results = self.check_all_parks()
            changes = self.compare_states(previous_state, current_results)
            
            if any(changes.values()):
                logging.info("상태 변화 감지 - 알림 발송")
                success = self.send_change_notification(changes, current_results)
            else:
                logging.info("상태 변화 없음")
                success = True
            
            self.save_current_state(current_results)
            return success
            
        except Exception as e:
            logging.error(f"체크 중 오류: {e}")
            error_message = f"❌ GitHub Actions 모니터링 오류\n\n{str(e)}\n\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)"
            self.send_telegram_message(error_message)
            return False

def main():
    monitor = GitHubActionsMonitor()
    success = monitor.run_single_check()
    
    if success:
        logging.info("모니터링 완료")
        sys.exit(0)
    else:
        logging.error("모니터링 실패")
        sys.exit(1)

if __name__ == "__main__":
    main()
