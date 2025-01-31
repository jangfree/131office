class RealTimeManager:
    def __init__(self):
        self.subscribed_codes = {}  # 구독 중인 종목 코드
        self.last_request_time = {}  # 마지막 요청 시간
        self.request_count = {}      # 요청 횟수 카운터
        self.MAX_CONCURRENT = 100    # 최대 동시 구독 수
        self.THROTTLE_INTERVAL = 0.2 # 요청 간격 (초)
        
    def subscribe_stock(self, code, screen_no):
        """실시간 데이터 구독 관리"""
        try:
            current_time = time.time()
            
            # 이미 구독 중인 경우 스킵
            if code in self.subscribed_codes:
                return True
                
            # 최대 구독 수 체크
            if len(self.subscribed_codes) >= self.MAX_CONCURRENT:
                oldest_code = min(self.last_request_time, key=self.last_request_time.get)
                self.unsubscribe_stock(oldest_code)
            
            # 스로틀링 적용
            if code in self.last_request_time:
                time_diff = current_time - self.last_request_time[code]
                if time_diff < self.THROTTLE_INTERVAL:
                    time.sleep(self.THROTTLE_INTERVAL - time_diff)
            
            # 실시간 데이터 등록
            self.subscribed_codes[code] = screen_no
            self.last_request_time[code] = current_time
            self.request_count[code] = self.request_count.get(code, 0) + 1
            
            return True
            
        except Exception as e:
            logging.error(f"실시간 데이터 구독 실패 ({code}): {str(e)}")
            return False
            
    def unsubscribe_stock(self, code):
        """실시간 데이터 구독 해제"""
        try:
            if code in self.subscribed_codes:
                screen_no = self.subscribed_codes[code]
                self.disconnect_real_data(screen_no)
                del self.subscribed_codes[code]
                del self.last_request_time[code]
                
        except Exception as e:
            logging.error(f"실시간 데이터 구독 해제 실패 ({code}): {str(e)}")

class KiwoomAPI(QAxWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")
        
        # 실시간 데이터 관리자 추가
        self.real_time_manager = RealTimeManager()
        
        # 메모리 관리를 위한 변수들
        self.data_cleanup_interval = 300  # 5분마다 정리
        self.last_cleanup_time = time.time()
        
        # 실시간 데이터 처리 큐 크기 제한
        self.real_time_queue = Queue(maxsize=1000)
        
    def _handler_real_data(self, code, real_type, real_data):
        """실시간 데이터 수신 이벤트 처리"""
        try:
            # 메모리 정리 체크
            current_time = time.time()
            if current_time - self.last_cleanup_time > self.data_cleanup_interval:
                self.cleanup_old_data()
                self.last_cleanup_time = current_time
            
            # 큐가 가득 찼을 경우 오래된 데이터 제거
            if self.real_time_queue.full():
                try:
                    self.real_time_queue.get_nowait()
                except Queue.Empty:
                    pass
            
            # 새 데이터 추가
            if real_type == "주식체결" and code in self.stock_data:
                data = {
                    'code': code,
                    'time': time.strftime("%H:%M:%S"),
                    'price': abs(float(self.get_comm_real_data(code, 10))),
                    'volume': abs(float(self.get_comm_real_data(code, 15))),
                    'change_rate': float(self.get_comm_real_data(code, 12))
                }
                
                self.real_time_queue.put(data)
                
        except Exception as e:
            logging.error(f"실시간 데이터 처리 실패 ({code}): {str(e)}")
            
    def cleanup_old_data(self):
        """오래된 데이터 정리"""
        try:
            current_time = time.time()
            codes_to_remove = []
            
            for code, stock in self.stock_data.items():
                # 30분 이상 업데이트 없는 데이터 제거
                if hasattr(stock, 'last_update_time'):
                    if current_time - stock.last_update_time > 1800:
                        codes_to_remove.append(code)
                        
            for code in codes_to_remove:
                del self.stock_data[code]
                self.real_time_manager.unsubscribe_stock(code)
                
        except Exception as e:
            logging.error(f"데이터 정리 실패: {str(e)}")

class MainWindow(QMainWindow):
    def startTrace(self):
        if not self.kiwoom.connected:
            QMessageBox.warning(self, "경고", "로그인이 필요합니다.")
            return

        try:
            self.is_running = True
            
            # 실시간 데이터 구독 시작
            for i in range(self.trace_stock_list.count()):
                code = self.trace_stock_list.item(i).text().split('-')[0].strip()
                screen_no = f"101{i:02d}"  # 각 종목별 고유한 화면번호 할당
                
                # 실시간 데이터 구독 요청
                if self.kiwoom.real_time_manager.subscribe_stock(code, screen_no):
                    self.kiwoom.set_real_reg(screen_no, code, "10;11;12;15;20", "0")
                    time.sleep(0.5)  # 요청 간격 조절
                
            # 처리 스레드 시작
            self.processing_thread = threading.Thread(target=self.processRealTimeData)
            self.processing_thread.daemon = True
            self.processing_thread.start()
            
        except Exception as e:
            logging.error(f"Trace 시작 실패: {str(e)}")
            self.is_running = False