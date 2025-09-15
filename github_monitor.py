#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions용 국립공원 예약 모니터링 - 디버깅 강화 버전
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
        self.debug_mode = True  # 디버깅 모드 활성화

    def save_debug_info(self, park_name, month, page_source, screenshot_path=None):
        """디버깅 정보 저장"""
        if not self.debug_mode:
            return
            
        debug_dir = 'debug_logs'
        os.makedirs(debug_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # HTML 소스 저장
        html_file = f"{debug_dir}/{park_name}_{month}월_{timestamp}.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(page_source)
        
        # 파싱된 텍스트 저장
        text_file = f"{debug_dir}/{park_name}_{month}월_{timestamp}_text.txt"
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(page_source)
        
        logging.info(f"디버그 파일 저장: {html_file}")

    def wait_for_page_load(self, driver, timeout=30):
        """페이지 완전 로딩 대기"""
        try:
            # 기본 페이지 로딩 대기
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # 추가 JavaScript 실행 완료 대기
            time.sleep(5)
            
            # 달력 요소가 로딩될 때까지 대기
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CLASS_NAME, "calendar"))
            )
            
            # 날짜 요소들이 로딩될 때까지 대기
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, "//td[contains(@class, 'calendar')]"))
            )
            
            logging.info("페이지 로딩 완료 확인")
            return True
            
        except Exception as e:
            logging.warning(f"페이지 로딩 대기 중 오류: {e}")
            return False

    def extract_visible_calendar_data(self, driver):
        """실제 화면에 표시되는 달력 데이터만 추출"""
        try:
            calendar_data = []
            
            # 달력 셀들 찾기 (여러 가능한 선택자 시도)
            possible_selectors = [
                "//td[contains(@class, 'calendar') and not(contains(@style, 'display: none'))]",
                "//td[@class='calendar']",
                "//div[contains(@class, 'day') and not(contains(@style, 'display: none'))]",
                "//span[contains(@class, 'date')]"
            ]
            
            calendar_cells = []
            for selector in possible_selectors:
                try:
                    cells = driver.find_elements(By.XPATH, selector)
                    if cells:
                        calendar_cells = cells
                        logging.info(f"달력 셀 발견: {len(cells)}개 (선택자: {selector})")
                        break
                except:
                    continue
            
            if not calendar_cells:
                logging.warning("달력 셀을 찾을 수 없음")
                return []
            
            for cell in calendar_cells:
                try:
                    # 셀이 실제로 보이는지 확인
                    if not cell.is_displayed():
                        continue
                    
                    cell_text = cell.text.strip()
                    if not cell_text:
                        continue
                    
                    # 날짜 추출
                    date_match = re.search(r'\b(\d{1,2})\b', cell_text)
                    if not date_match:
                        continue
                    
                    day = int(date_match.group(1))
                    
                    # 잔여 개수 추출
                    remaining_match = re.search(r'생활관\s*:\s*잔여\s*(\d+)\s*개', cell_text)
                    if remaining_match:
                        remaining = int(remaining_match.group(1))
                        
                        calendar_data.append({
                            'day': day,
                            'remaining': remaining,
                            'cell_text': cell_text,
                            'is_clickable': cell.is_enabled()
                        })
                        
                        logging.info(f"발견된 예약 가능 날짜: {day}일, 잔여 {remaining}개")
                
                except Exception as e:
                    logging.debug(f"셀 파싱 오류: {e}")
                    continue
            
            return calendar_data
            
        except Exception as e:
            logging.error(f"달력 데이터 추출 실패: {e}")
            return []

    def parse_weekend_availability_enhanced(self, driver, month):
        """향상된 주말 예약 파싱 (실제 화면 데이터 기반)"""
        available_dates = []
        
        try:
            # 페이지 완전 로딩 대기
            self.wait_for_page_load(driver)
            
            # 스크린샷 저장 (디버깅용)
            if self.debug_mode:
                screenshot_path = f"debug_logs/screenshot_{month}월_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                driver.save_screenshot(screenshot_path)
                logging.info(f"스크린샷 저장: {screenshot_path}")
            
            # 페이지 소스 저장 (디버깅용)
            page_source = driver.page_source
            self.save_debug_info("current", month, page_source)
            
            # 실제 화면에 보이는 달력 데이터 추출
            calendar_data = self.extract_visible_calendar_data(driver)
            
            # 주말 날짜만 필터링
            for data in calendar_data:
                day = data['day']
                remaining = data['remaining']
                
                if remaining <= 0:
                    continue
                
                try:
                    date_obj = datetime(self.target_year, month, day)
                    weekday_num = date_obj.weekday()
                    
                    # 주말 (금요일=4, 토요일=5)만 포함
                    if weekday_num in self.weekend_days:
                        weekday_name = "금요일" if weekday_num == 4 else "토요일"
                        
                        date_info = {
                            'date': f"{self.target_year}-{month:02d}-{day:02d}",
                            'weekday': weekday_name,
                            'remaining': remaining
                        }
                        
                        available_dates.append(date_info)
                        logging.info(f"✅ 유효한 주말 예약: {date_info}")
                    else:
                        logging.debug(f"⏭️ 주말 아님: {day}일 ({weekday_num})")
                        
                except ValueError as e:
                    logging.warning(f"⚠️ 잘못된 날짜: {day}일 - {e}")
                    continue
            
            # 기존 방식과 비교 (디버깅)
            if self.debug_mode:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                old_results = self.parse_weekend_availability_old(body_text, month)
                
                logging.info(f"🔍 새 방식 결과: {len(available_dates)}개")
                logging.info(f"🔍 기존 방식 결과: {len(old_results)}개")
                
                # 차이점 로깅
                new_dates = {d['date'] for d in available_dates}
                old_dates = {d['date'] for d in old_results}
                
                if new_dates != old_dates:
                    logging.warning(f"⚠️ 방식별 결과 차이 발견!")
                    logging.warning(f"새 방식만: {new_dates - old_dates}")
                    logging.warning(f"기존 방식만: {old_dates - new_dates}")
            
            return available_dates
            
        except Exception as e:
            logging.error(f"향상된 파싱 실패: {e}")
            # 기존 방식으로 폴백
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                return self.parse_weekend_availability_old(body_text, month)
            except:
                return []

    def parse_weekend_availability_old(self, page_text, month):
        """기존 파싱 방식 (비교용)"""
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
            logging.error(f"기존 파싱 실패: {e}")
            return []

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
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--disable-features=VizDisplayCompositor')
        
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

    def check_park_availability(self, park_name):
        """공원 체크"""
        driver = self.setup_driver()
        if not driver:
            return {}
            
        try:
            logging.info(f"🌲 {park_name} 페이지 접속 중...")
            driver.get(self.url)
            time.sleep(10)
            
            park_link = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{park_name}')]"))
            )
            park_link.click()
            time.sleep(5)
            
            result = {}
            
            for month in self.target_months:
                logging.info(f"📅 {park_name} {month}월 데이터 수집 중...")
                
                if not self.navigate_to_month(driver, month):
                    logging.warning(f"❌ {month}월로 이동 실패")
                    continue
                
                # 향상된 파싱 사용
                available_dates = self.parse_weekend_availability_enhanced(driver, month)
                
                month_name = f"{month}월"
                result[month_name] = available_dates
                
                logging.info(f"✅ {park_name} {month}월: {len(available_dates)}개 예약 가능")
            
            return result
        except Exception as e:
            logging.error(f"❌ {park_name} 체크 실패: {e}")
            return {}
        finally:
            if driver:
                driver.quit()

    def check_all_parks(self):
        """모든 공원 체크"""
        all_results = {}
        
        for park_name in self.parks.keys():
            logging.info(f"🏔️ {park_name} 체크 중...")
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
        logging.info("🚀 GitHub Actions 모니터링 시작")
        
        try:
            previous_state = self.load_previous_state()
            current_results = self.check_all_parks()
            changes = self.compare_states(previous_state, current_results)
            
            if any(changes.values()):
                logging.info("📢 상태 변화 감지 - 알림 발송")
                success = self.send_change_notification(changes, current_results)
            else:
                logging.info("🔄 상태 변화 없음")
                success = True
            
            self.save_current_state(current_results)
            return success
            
        except Exception as e:
            logging.error(f"💥 체크 중 오류: {e}")
            error_message = f"❌ GitHub Actions 모니터링 오류\n\n{str(e)}\n\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC)"
            self.send_telegram_message(error_message)
            return False

def main():
    monitor = GitHubActionsMonitor()
    success = monitor.run_single_check()
    
    if success:
        logging.info("✅ 모니터링 완료")
        sys.exit(0)
    else:
        logging.error("❌ 모니터링 실패")
        sys.exit(1)

if __name__ == "__main__":
    main()
