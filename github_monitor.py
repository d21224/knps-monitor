#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions용 국립공원 예약 모니터링 - 당월/익월 자동 체크
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
        
        # 현재 날짜 기준으로 당월과 익월 설정
        now = datetime.now()
        self.target_year = now.year
        self.target_months = [now.month, (now.month % 12) + 1]
        
        # 익월이 1월인 경우 연도 조정
        if self.target_months[1] == 1:
            self.next_year = self.target_year + 1
        else:
            self.next_year = self.target_year
        
        self.weekend_days = [4, 5]  # 금요일, 토요일
        
        # 모니터링할 공원 설정
        self.parks = {
            '북한산': 'B971002', '변산반도': 'B183001', '한려해상': 'B024002'
        }
        
        # 비활성화된 공원들 (필요시 위에 추가)
        # '지리산': 'B014003', '무등산': 'B061002', '내장산': 'B063002', '설악산': 'B301002', '소백산': 'B123002', '가야산': 'B051001'
        
        self.telegram_config = {
            'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN'),
            'chat_id': os.environ.get('TELEGRAM_CHAT_ID'),
        }
        
        if not self.telegram_config['bot_token'] or not self.telegram_config['chat_id']:
            logging.error("텔레그램 설정이 없습니다. GitHub Secrets를 확인하세요.")
            sys.exit(1)
        
        self.state_file = 'knps_state.json'
        
        logging.info(f"모니터링 대상: {self.target_year}년 {self.target_months[0]}월, {self.next_year}년 {self.target_months[1]}월")

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
            current_month = None
            
            # 현재 표시된 월 찾기
            for elem in month_elements:
                text = elem.text
                match = re.search(r'(\d+)월', text)
                if match:
                    current_month = int(match.group(1))
                    break
            
            if current_month is None:
                logging.error("현재 월을 찾을 수 없습니다")
                return False
            
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

    def parse_weekend_availability(self, driver, month, year):
        """주말 예약 파싱"""
        available_dates = []
        
        try:
            # 페이지 로딩 완료 대기
            time.sleep(3)
            
            # 달력 셀들 찾기 - data 속성을 가진 요소들만
            calendar_cells = driver.find_elements(By.CSS_SELECTOR, ".calendar-cell[data-deptid][data-usedt]")
            
            for cell in calendar_cells:
                try:
                    # 예약 가능 조건 확인 (웹페이지와 동일한 로직)
                    prd_sal_stcd = cell.get_attribute("data-prdsalstcd")  # 판매 상태
                    cal_yn = cell.get_attribute("data-calyn")  # 달력 활성화 여부
                    
                    # 예약 불가능한 경우 스킵 (JavaScript 조건과 동일)
                    if (prd_sal_stcd != 'N' and prd_sal_stcd != 'R') or cal_yn != 'Y':
                        continue
                    
                    # 날짜 추출
                    day_element = cell.find_element(By.CSS_SELECTOR, ".day")
                    day = int(day_element.text.strip())
                    
                    # 잔여 개수 추출
                    try:
                        contents_ul = cell.find_element(By.CSS_SELECTOR, "ul.contents")
                        remaining_text = contents_ul.text
                        remaining_match = re.search(r'생활관\s*:\s*잔여\s*(\d+)\s*개', remaining_text)
                        
                        if remaining_match:
                            remaining = int(remaining_match.group(1))
                            
                            # 잔여가 0개면 스킵
                            if remaining <= 0:
                                continue
                            
                            # 주말 확인
                            try:
                                date_obj = datetime(year, month, day)
                                weekday_num = date_obj.weekday()
                                
                                if weekday_num in self.weekend_days:
                                    weekday_name = "금요일" if weekday_num == 4 else "토요일"
                                    available_dates.append({
                                        'date': f"{year}-{month:02d}-{day:02d}",
                                        'weekday': weekday_name,
                                        'remaining': remaining
                                    })
                                    
                                    logging.info(f"유효한 예약 발견: {month}월 {day}일 ({weekday_name}) - 잔여 {remaining}개")
                                    
                            except ValueError:
                                continue
                                
                    except:
                        # contents가 없는 경우 (잔여 정보 없음)
                        continue
                        
                except Exception as e:
                    logging.debug(f"셀 파싱 중 오류: {e}")
                    continue
            
            logging.info(f"{month}월 파싱 완료: {len(available_dates)}개 예약 가능")
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
            
            # 당월 체크
            if not self.navigate_to_month(driver, self.target_months[0]):
                logging.warning(f"{self.target_months[0]}월로 이동 실패")
            else:
                available_dates = self.parse_weekend_availability(driver, self.target_months[0], self.target_year)
                month_name = f"{self.target_months[0]}월"
                result[month_name] = available_dates
            
            # 익월 체크
            if not self.navigate_to_month(driver, self.target_months[1]):
                logging.warning(f"{self.target_months[1]}월로 이동 실패")
            else:
                available_dates = self.parse_weekend_availability(driver, self.target_months[1], self.next_year)
                month_name = f"{self.target_months[1]}월"
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

    def send_change_notification(self, changes, current_results):
        """간단한 현재 예약 현황 알림"""
        if not any(changes.values()):
            return False
            
        message = f"""🏞️ 국립공원 예약 현황 업데이트

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)

📋 현재 예약 가능:

"""
        
        # 현재 전체 예약 가능 상황만 표시
        total_available = 0
        for park_name, months_data in current_results.items():
            park_has_availability = False
            park_dates = []
            
            for month_name, dates in months_data.items():
                if dates:
                    park_has_availability = True
                    park_dates.extend(dates)
                    total_available += len(dates)
            
            if park_has_availability:
                message += f"🏔️ {park_name}\n"
                for date_info in park_dates:
                    message += f"  • {date_info['date']} ({date_info['weekday']}) - 잔여 {date_info['remaining']}개\n"
                message += "\n"
        
        if total_available == 0:
            message += "❌ 현재 예약 가능한 주말 없음\n\n"
        else:
            message += f"📊 총 {total_available}개 주말 날짜 예약 가능\n\n"
        
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
