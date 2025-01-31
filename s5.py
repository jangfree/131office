#위의 소스를 실행해보면  trace 종목명 리스트에 여러 종목을 trace 하라고 선택했는데 로그파일의 기록에는 거의 1개의 종목만 집중해서 실시간 tick 정보가 남아있는 사유는? 32bit 파이썬 환경에서 보수적인 방식으로 해결방안은?
#특정 종목 정보만 실시간정보로 넘어오는 문제 
import sys
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5 import uic
from PyQt5.QtWidgets import *
#from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QAxContainer import QAxWidget
import pythoncom
from PyQt5.QtCore import QObject, pyqtSignal
#from PyQt5.QtCore import SIGNAL  # 추가
#from pykiwoom.kiwoom import *
import time
#import pandas as pd
from collections import defaultdict
import threading
from queue import Queue
import logging

# 로깅 설정
logging.basicConfig(
    filename='trading_log.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class KiwoomAPI(QAxWidget):

     #신호 추가: 거래량 체크 요청 시 code 전달
    #volume_check_requested = pyqtSignal(str)

    def __init__(self, parent=None):  # parent 인자 추가
        super().__init__()
        self.parent = parent  # 상위 윈도우 참조 저장
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")
        
        # 이벤트 핸들러 등록
        self.OnEventConnect.connect(self._handler_login)
        self.OnReceiveTrData.connect(self._handler_tr_data)
        self.OnReceiveRealData.connect(self._handler_real_data)
        self.OnReceiveConditionVer.connect(self._handler_condition_ver)
        self.OnReceiveTrCondition.connect(self._handler_tr_condition)
        self.OnReceiveRealCondition.connect(self._handler_real_condition)
        
        # 데이터 관리용 변수들
        self.connected = False
        self.tr_event_loop = QEventLoop()
        self.condition_event_loop = QEventLoop()
        self.conditions = {}
        self.stock_data = {}
        self.real_time_queue = Queue()

    def connect(self):
        """로그인 수행"""
        self.dynamicCall("CommConnect()")
        self.login_event_loop = QEventLoop()
        self.login_event_loop.exec_()

    def _handler_login(self, err_code):
        """로그인 결과 처리"""
        if err_code == 0:
            self.connected = True
            logging.info("로그인 성공")
        else:
            logging.error(f"로그인 실패: {err_code}")
        
        if hasattr(self, 'login_event_loop'):
            self.login_event_loop.exit()

    def get_condition_load(self):
        """조건식 목록 불러오기"""
        self.dynamicCall("GetConditionLoad()")
        self.condition_event_loop = QEventLoop()
        self.condition_event_loop.exec_()

    


    def _handler_condition_ver(self, ret, msg):
        """조건식 목록 로드 결과"""
        try:
            if ret == 1:
                logging.info("조건식 로드 성공")
                # 조건식 목록 가져오기
                conditions = self.dynamicCall("GetConditionNameList()")
                if conditions:
                    self.parent.condition_list.clear()
                    condition_list = conditions.split(';')[:-1]  # 마지막 빈 항목 제거
                    for condition in condition_list:
                        parts = condition.split('^')
                        if len(parts) >= 2:
                            index = parts[0]
                            name = parts[1]
                            self.parent.condition_list.addItem(f"{index}:{name}")
            else:
                logging.error(f"조건식 로드 실패: {msg}")
            
            if hasattr(self, 'condition_event_loop'):
                self.condition_event_loop.exit()
                
        except Exception as e:
            logging.error(f"조건식 버전 처리 실패: {str(e)}")



    def send_condition(self, screen_no, condition_name, index, search_type):
        """조건검색 실행"""
        ret = self.dynamicCall("SendCondition(QString, QString, int, int)",
                             screen_no, condition_name, index, search_type)
        if ret == 1:
            logging.info(f"조건검색 요청 성공: {condition_name}")
        else:
            logging.error(f"조건검색 요청 실패: {condition_name}")
        return ret

    def get_master_code_name(self, code):
        """종목코드로 종목명 조회"""
        return self.dynamicCall("GetMasterCodeName(QString)", code)

    def set_real_reg(self, screen_no, code_list, fid_list, real_type):
        """실시간 데이터 등록"""
        self.dynamicCall("SetRealReg(QString, QString, QString, QString)",
                        screen_no, code_list, fid_list, real_type)

    def get_comm_real_data(self, code, fid):
        """실시간 데이터 조회"""
        return self.dynamicCall("GetCommRealData(QString, int)", code, fid)

    def get_comm_data(self, trcode, rqname, index, item):
        """TR 데이터 조회"""
        return self.dynamicCall("GetCommData(QString, QString, int, QString)",
                              trcode, rqname, index, item).strip()

    def disconnect_real_data(self, screen_no):
        """실시간 데이터 해제"""
        self.dynamicCall("DisconnectRealData(QString)", screen_no)

    def _handler_tr_data(self, screen_no, rqname, trcode, record_name, next, unused1, unused2, unused3, unused4):
        """TR 수신 이벤트"""
        try:
            if rqname == "opt10081_req":  # 분봉 데이터 요청
                data_count = self.GetRepeatCnt(trcode, rqname)
                code = self.GetCommData(trcode, rqname, 0, "종목코드").strip()
                
                volumes = []
                for i in range(data_count):
                    volume = int(self.GetCommData(trcode, rqname, i, "거래량"))
                    volumes.append(volume)
                
                if code in self.stock_data:
                    self.stock_data[code]['three_min_volumes'] = volumes
                
            self.tr_event_loop.exit()
        except Exception as e:
            logging.error(f"TR 데이터 처리 실패: {str(e)}")

    def _handler_real_data(self, code, real_type, real_data):
        """실시간 데이터 수신 이벤트"""
        try:
            if real_type == "주식체결" and code in self.stock_data:
                stock = self.stock_data[code]
                
                # 현재가, 거래량 등 업데이트
                current_price = abs(float(self.get_comm_real_data(code, 10)))
                current_volume = abs(float(self.get_comm_real_data(code, 15)))
                change_rate = float(self.get_comm_real_data(code, 12))
                change_amount = float(self.get_comm_real_data(code, 11))
                
                # 가격 상승 여부 체크
                stock.price_up = current_price > stock.current_price
                
                # 데이터 업데이트
                stock.current_price = current_price
                stock.current_volume = current_volume
                stock.change_rate = change_rate
                stock.change_amount = change_amount
                
                # 분봉 데이터 업데이트 (StockData의 메서드 호출)
                current_time = time.strftime("%H%M%S")
                stock.updateMinuteData(current_time, current_volume)  # 수정된 부분
                
                # 거래량 조건 체크
                # 거래량 조건 체크 (직접 호출 대신 신호 발생)
                if stock.price_up and self.parent:
                    self.parent.checkVolumeConditions(code)
                    #self.volume_check_requested.emit(code)  # 수정된 부분

                # 실시간 데이터 로깅
                self.logTraceData("realtime",
                                code=code,
                                name=stock.name,
                                price=current_price,
                                volume=current_volume,
                                change_rate=change_rate)
                
        except Exception as e:
            logging.error(f"실시간 데이터 처리 실패: {str(e)}")

    def _handler_tr_condition(self, screen_no, codes, condition_name, index, next):
        """조건검색 TR 이벤트"""
        try:
            if codes:
                codes_list = codes.split(';')[:-1]
                for code in codes_list:
                    name = self.get_master_code_name(code)
                    if self.isTraceTarget(code):
                        current_time = time.strftime("%H:%M:%S")
                        price = self.get_comm_real_data(code, 10)
                        change_rate = self.get_comm_real_data(code, 12)
                        change_amount = self.get_comm_real_data(code, 11)
                        
                        self.addToRecommendedTable(
                            current_time, condition_name, code, name,
                            price, change_rate, change_amount
                        )
        except Exception as e:
            logging.error(f"조건검색 TR 처리 실패: {str(e)}")

    def _handler_real_condition(self, code, event_type, condition_name, condition_index):
        """실시간 조건검색 이벤트"""
        try:

            if not code or len(code) < 6:  # 유효한 종목코드인지 확인
                return

            if event_type == "I":  # 종목 편입
                if self.isTraceTarget(code):
                    current_time = time.strftime("%H:%M:%S")
                    name = self.get_master_code_name(code)
                    try:
                        price = float(self.get_comm_real_data(code, 10))
                        change_rate = float(self.get_comm_real_data(code, 12))
                        change_amount = float(self.get_comm_real_data(code, 11))
                    except:
                        logging.error(f"실시간 데이터 파싱 실패: {code}")
                        return
                    
                    # 조건검색 결과 로깅
                    self.logTraceData("condition",
                                    condition_name=condition_name,
                                    code=code,
                                    name=name,
                                    price=price,
                                    change_rate=change_rate)
                    
                    self.addToRecommendedTable(
                        current_time, condition_name, code, name,
                        price, change_rate, change_amount
                    )
        except Exception as e:
            logging.error(f"실시간 조건검색 처리 실패: {str(e)}")

    def isTraceTarget(self, code):
        """Trace 대상 종목인지 확인"""
        if hasattr(self, 'parent'):
            for i in range(self.parent.trace_stock_list.count()):
                if code in self.parent.trace_stock_list.item(i).text():
                    return True
        return False

    def addToRecommendedTable(self, time, condition, code, name, price, rate, amount):
        """조건검색 추천종목 테이블에 추가"""
        if hasattr(self, 'parent'):
            self.parent.addToRecommendedTable(time, condition, code, name, price, rate, amount)

    def logTraceData(self, data_type, **kwargs):
        """Trace 데이터 로깅"""
        try:
            if not self.connected or not self.real_time_queue.empty():
                return
                
            current_time = time.strftime("%H:%M:%S")
            
            with open('trading_log.txt', 'a', encoding='utf-8') as f:
                if data_type == "condition":
                    # 조건검색식 결과 로깅
                    f.write(f"[조건검색] {current_time} | "
                           f"조건: {kwargs.get('condition_name')} | "
                           f"종목: {kwargs.get('code')} - {kwargs.get('name')} | "
                           f"가격: {kwargs.get('price')} | "
                           f"등락률: {kwargs.get('change_rate')}%\n")
                
                elif data_type == "realtime":
                    # 실시간 종목 정보 로깅
                    f.write(f"[실시간] {current_time} | "
                           f"종목: {kwargs.get('code')} - {kwargs.get('name')} | "
                           f"가격: {kwargs.get('price')} | "
                           f"거래량: {kwargs.get('volume')} | "
                           f"등락률: {kwargs.get('change_rate')}%\n")
                
        except Exception as e:
            logging.error(f"데이터 로깅 실패: {str(e)}")

class StockData:
    def __init__(self, code, name):
        self.code = code
        self.name = name
        self.prev_day_volume = 0
        self.current_price = 0
        self.current_volume = 0
        self.change_rate = 0
        self.change_amount = 0
        self.price_up = False
        self.minute_data = []  # 1분봉 데이터
        self.three_min_data = []  # 3분봉 데이터
        self.current_minute_volume = 0
        self.current_three_min_volume = 0
        self.last_update_time = None

    def updateMinuteData(self, current_time_str, current_volume):
        """분봉 데이터 업데이트"""
        try:
            current_minute = current_time_str[:4]  # 'HHMM' 형식

            # 새로운 분봉 시작 체크
            if self.last_update_time != current_minute:
                self.minute_data.append({
                    'time': current_time_str,
                    'volume': current_volume
                })
                
                # 1분봉 데이터 최대 30개 유지
                if len(self.minute_data) > 30:
                    self.minute_data.pop(0)
                
                # 3분봉 데이터 업데이트 (3분마다)
                if len(self.minute_data) % 3 == 0:
                    three_min_volume = sum(item['volume'] for item in self.minute_data[-3:])
                    self.three_min_data.append({
                        'time': current_time_str,
                        'volume': three_min_volume
                    })
                    
                    # 3분봉 데이터 최대 10개 유지
                    if len(self.three_min_data) > 10:
                        self.three_min_data.pop(0)

                self.last_update_time = current_minute

        except Exception as e:
            logging.error(f"분봉 업데이트 실패 ({self.code}): {str(e)}")



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.kiwoom = KiwoomAPI(self)  # parent로 자신을 전달
        self.setupUI()

        # 신호 연결 추가
        #self.kiwoom.volume_check_requested.connect(self.checkVolumeConditions)  # 추가된 코드
        #self.kiwoom.connect(SIGNAL("volume_check_requested(QString)"), self.checkVolumeConditions)
        self.is_running = False
        self.processing_thread = None
        self.is_logging = False  # 로깅 상태
        self.current_log_file = None
        
        # 실시간 데이터 처리를 위한 타이머 설정
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_real_time_data)
        self.timer.start(100)  # 100ms 간격으로 실행

    def setupUI(self):
        # 메인 윈도우 설정 - 크기 증가
        self.setWindowTitle("트레이딩 시스템")
        self.setGeometry(100, 100, 1800, 1000)  # 크기를 1800x1000으로 증가
        
        # 중앙 위젯 생성
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 테이블 위젯들 초기화
        self.recommended_table = QTableWidget()
        self.volume_2x_table = QTableWidget()
        self.volume_3x_table = QTableWidget()
        
        # 메인 레이아웃
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)  # 위젯 간 간격 설정
        
        # 상단 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)  # 버튼 간 간격 설정
        self.login_btn = QPushButton("로그인")
        self.interest_btn = QPushButton("관심종목군 가져오기")
        self.condition_btn = QPushButton("조건검색식 가져오기")
        self.trace_start_btn = QPushButton("Trace 시작")
        self.trace_stop_btn = QPushButton("Trace 중단")
        self.logging_btn = QPushButton("Trace 로깅 시작")
        
        # 버튼 크기 설정
        for btn in [self.login_btn, self.interest_btn, self.condition_btn, 
                   self.trace_start_btn, self.trace_stop_btn, self.logging_btn]:
            btn.setMinimumHeight(40)  # 버튼 높이 설정
            button_layout.addWidget(btn)
            
        layout.addLayout(button_layout)
        
        # 리스트 영역
        list_layout = QHBoxLayout()
        list_layout.setSpacing(20)  # 리스트 간 간격 설정
        
        # 왼쪽 영역
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        
        # 관심종목군 그룹
        interest_group = QGroupBox("관심종목군")
        interest_layout = QVBoxLayout()
        self.interest_group_list = QListWidget()
        self.interest_group_list.setMinimumWidth(300)  # 최소 너비 설정
        self.interest_group_list.setMinimumHeight(400)  # 최소 높이 설정
        interest_layout.addWidget(self.interest_group_list)
        interest_group.setLayout(interest_layout)
        
        # 종목 리스트 그룹
        stock_group = QGroupBox("종목 리스트")
        stock_layout = QVBoxLayout()
        self.stock_list = QListWidget()
        self.stock_list.setMinimumWidth(300)
        self.stock_list.setMinimumHeight(400)
        stock_layout.addWidget(self.stock_list)
        stock_group.setLayout(stock_layout)
        
        left_layout.addWidget(interest_group)
        left_layout.addWidget(stock_group)
        
        # 중앙 영역
        middle_layout = QVBoxLayout()
        middle_layout.setSpacing(10)
        
        # Trace 종목명 리스트 그룹
        trace_stock_group = QGroupBox("Trace 종목명 리스트")
        trace_stock_layout = QVBoxLayout()
        self.trace_stock_list = QListWidget()
        self.trace_stock_list.setMinimumWidth(300)
        self.trace_stock_list.setMinimumHeight(400)
        trace_stock_layout.addWidget(self.trace_stock_list)
        trace_stock_group.setLayout(trace_stock_layout)
        
        # 조건검색식 리스트 그룹
        condition_group = QGroupBox("조건검색식 리스트")
        condition_layout = QVBoxLayout()
        self.condition_list = QListWidget()
        self.condition_list.setMinimumWidth(300)
        self.condition_list.setMinimumHeight(400)
        condition_layout.addWidget(self.condition_list)
        condition_group.setLayout(condition_layout)
        
        middle_layout.addWidget(trace_stock_group)
        middle_layout.addWidget(condition_group)
        
        # 오른쪽 영역
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)
        
        # Trace 조건검색식 리스트 그룹
        trace_condition_group = QGroupBox("Trace 조건검색식 리스트")
        trace_condition_layout = QVBoxLayout()
        self.trace_condition_list = QListWidget()
        self.trace_condition_list.setMinimumWidth(300)
        self.trace_condition_list.setMinimumHeight(200)
        trace_condition_layout.addWidget(self.trace_condition_list)
        trace_condition_group.setLayout(trace_condition_layout)
        right_layout.addWidget(trace_condition_group)
        
        # 테이블 그룹들
        for table_info in [
            ("조건검색식 추천종목", self.recommended_table),
            ("거래량 2배 증가 종목", self.volume_2x_table),
            ("거래량 3배 증가 종목", self.volume_3x_table)
        ]:
            group = QGroupBox(table_info[0])
            table_layout = QVBoxLayout()
            table = table_info[1]
            self.setupTable(table)
            table.setMinimumWidth(500)  # 테이블 최소 너비 설정
            table.setMinimumHeight(200)  # 테이블 최소 높이 설정
            table_layout.addWidget(table)
            group.setLayout(table_layout)
            right_layout.addWidget(group)
        
        list_layout.addLayout(left_layout)
        list_layout.addLayout(middle_layout)
        list_layout.addLayout(right_layout)
        
        layout.addLayout(list_layout)
        
        # 시그널 연결
        self.connectSignals()

    def setupTable(self, table):
        """테이블 설정"""
        headers = ["발생시간", "조건검색식", "종목코드", "종목명", "현재가", "등락율", "증감금액"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        
        # 각 컬럼 너비 설정
        table.setColumnWidth(0, 80)  # 발생시간
        table.setColumnWidth(1, 150)  # 조건검색식
        table.setColumnWidth(2, 80)  # 종목코드
        table.setColumnWidth(3, 100)  # 종목명
        table.setColumnWidth(4, 80)  # 현재가
        table.setColumnWidth(5, 80)  # 등락율
        table.setColumnWidth(6, 80)  # 증감금액

    def connectSignals(self):
        self.login_btn.clicked.connect(self.login)
        self.interest_btn.clicked.connect(self.loadInterestGroups)
        self.condition_btn.clicked.connect(self.loadConditions)
        self.trace_start_btn.clicked.connect(self.startTrace)
        self.trace_stop_btn.clicked.connect(self.stopTrace)
        self.logging_btn.clicked.connect(self.toggleLogging)
        
        # 더블클릭 이벤트
        self.interest_group_list.itemDoubleClicked.connect(self.showGroupStocks)
        self.stock_list.itemDoubleClicked.connect(self.addToTraceList)
        self.condition_list.itemDoubleClicked.connect(self.addToTraceCondition)

    def login(self):
        """로그인 버튼 클릭 처리"""
        try:
            self.kiwoom.connect()
            if self.kiwoom.connected:
                QMessageBox.information(self, "알림", "로그인 성공")
                self.kiwoom.get_condition_load()  # 조건식 로드
        except Exception as e:
            logging.error(f"로그인 처리 중 오류: {str(e)}")
            QMessageBox.critical(self, "오류", f"로그인 실패: {str(e)}")

    def loadInterestGroups(self):
        try:
            with open('interest.txt', 'r', encoding='utf-8') as f:
                codes = f.read().split(':')
                for code in codes:
                    code = code.strip()
                    if code:
                        # TR 요청 제한 고려
                        time.sleep(0.2)
                        name = self.kiwoom.get_master_code_name(code)
                        if name:
                            self.interest_group_list.addItem(f"{code} - {name}")
                            # 실시간 시세 등록
                            self.kiwoom.set_real_reg("0101", code, "10;11;12;15;20", "0")
        except Exception as e:
            logging.error(f"관심종목 로드 실패: {str(e)}")

    def loadConditions(self):
        """조건검색식 가져오기 버튼 클릭 처리"""
        try:
            self.condition_list.clear()  # 기존 목록 초기화
            
            # 조건식 목록 요청
            ret = self.kiwoom.dynamicCall("GetConditionLoad()")
            
            if ret == 1:
                # 조건식 목록 대기
                self.kiwoom.condition_event_loop = QEventLoop()
                self.kiwoom.condition_event_loop.exec_()
                
                # 조건식 목록 가져오기
                conditions = self.kiwoom.dynamicCall("GetConditionNameList()")
                
                if conditions:
                    condition_list = conditions.split(';')
                    for condition in condition_list[:-1]:  # 마지막 빈 문자열 제외
                        index, name = condition.split('^')
                        self.condition_list.addItem(f"{index}:{name}")
                    QMessageBox.information(self, "알림", "조건식 불러오기 완료")
                else:
                    QMessageBox.warning(self, "경고", "사용할 수 있는 조건식이 없습니다")
            else:
                QMessageBox.critical(self, "오류", "조건식 불러오기 실패")
            
        except Exception as e:
            logging.error(f"조건식 로드 실패: {str(e)}")
            QMessageBox.critical(self, "오류", f"조건식 로드 중 오류 발생: {str(e)}")

    def startTrace(self):
        if not self.kiwoom.connected:
            QMessageBox.warning(self, "경고", "로그인이 필요합니다.")
            return

        try:
            self.is_running = True
            
            # 조건검색식 실시간 감시 시작
            #for i in range(self.trace_condition_list.count()):
            #    condition = self.trace_condition_list.item(i).text()
            #    condition_index = condition.split(':')[0]
            #    self.kiwoom.send_condition("0156", condition, int(condition_index), 1)  # 1: 실시간 감시

            # 조건검색식 실시간 감시 시작
            for i in range(self.trace_condition_list.count()):
                condition_item = self.trace_condition_list.item(i).text()
                condition_index, condition_name = condition_item.split(':', 1)  # 수정: 첫번째 ':'만 분리
                
                try:
                    condition_index = int(condition_index)
                except ValueError:
                    logging.error(f"유효하지 않은 조건식 인덱스: {condition_index}")
                    continue

                if condition_index < 0:
                    logging.error(f"음수 조건식 인덱스: {condition_index}")
                    continue

                # 고유한 화면번호 생성 (1000 + 조건식 인덱스)
                screen_no = str(1000 + int(condition_index))
                
                # 조건검색 요청
                ret = self.kiwoom.send_condition(screen_no, condition_name, int(condition_index), 1)
                
                if ret == 1:
                    logging.info(f"조건검색 시작 성공: {condition_name}")
                else:
                    logging.error(f"조건검색 시작 실패: {condition_name}")    
                    
                
                
                
                time.sleep(0.5)  # 부하 조절
                
            # Trace 종목 실시간 데이터 수신 시작
            for i in range(self.trace_stock_list.count()):
                code = self.trace_stock_list.item(i).text().split('-')[0].strip()
                self.initializeStockData(code)
                self.kiwoom.set_real_reg("0101", code, "10;11;12;15;20", "0")
                time.sleep(0.2)  # 부하 조절
                
            # 실시간 데이터 처리 스레드 시작
            self.processing_thread = threading.Thread(target=self.processRealTimeData)
            self.processing_thread.daemon = True
            self.processing_thread.start()
            
        except Exception as e:
            logging.error(f"Trace 시작 실패: {str(e)}")
            self.is_running = False

    def initializeStockData(self, code):
        """종목 초기 데이터 설정"""
        try:
            # 종목 데이터 구조체 생성
            stock = StockData(code, self.kiwoom.get_master_code_name(code))
            
            # TR 요청으로 초기 데이터 설정
            self.requestStockData(code, stock)
            
            # 실시간 데이터 등록
            self.kiwoom.set_real_reg("0101", code, "10;11;12;15;20", "0")
            
            # 데이터 저장
            self.kiwoom.stock_data[code] = stock
            
        except Exception as e:
            logging.error(f"종목 데이터 초기화 실패 ({code}): {str(e)}")

    def requestStockData(self, code, stock):
        """종목의 초기 데이터 요청"""
        try:
            # 전일 거래량 조회 (opt10081은 일봉 조회 TR)
            self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
            self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "기준일자", "20240524")  # 당일 날짜로 변경 필요
            self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "0")
            self.kiwoom.dynamicCall("CommRqData(QString, QString, int, QString)", "opt10081_req", "opt10081", 0, "0101")
            
            # TR 응답 대기
            self.kiwoom.tr_event_loop.exec_()
            
            # 전일 거래량 저장
            daily_volume = self.kiwoom.get_comm_data("opt10081", "opt10081_req", 0, "거래량")
            stock.prev_day_volume = int(daily_volume) if daily_volume.strip() else 0
            
            # 분봉 데이터 요청 (opt10080은 분봉 조회 TR)
            self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
            self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "틱범위", "1")  # 1분봉
            self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "0")
            self.kiwoom.dynamicCall("CommRqData(QString, QString, int, QString)", "opt10080_req", "opt10080", 0, "0101")
            
            # TR 응답 대기
            self.kiwoom.tr_event_loop.exec_()
            
            # 분봉 데이터 처리
            data_count = self.kiwoom.dynamicCall("GetRepeatCnt(QString, QString)", "opt10080", "opt10080_req")
            for i in range(data_count):
                minute_time = self.kiwoom.get_comm_data("opt10080", "opt10080_req", i, "체결시간")
                volume = self.kiwoom.get_comm_data("opt10080", "opt10080_req", i, "거래량")
                
                if minute_time and volume:
                    stock.minute_data.append({
                        'time': minute_time.strip(),
                        'volume': int(volume.strip())
                    })
            
            # 3분봉 데이터 계산
            three_min_volume = 0
            for idx, data in enumerate(stock.minute_data):
                three_min_volume += data['volume']
                if (idx + 1) % 3 == 0:
                    stock.three_min_data.append({
                        'time': data['time'],
                        'volume': three_min_volume
                    })
                    three_min_volume = 0
            
        except Exception as e:
            logging.error(f"데이터 요청 실패: {str(e)}")

    def processRealTimeData(self):
        """실시간 데이터 처리 메인 로직"""
        while self.is_running:
            try:
                if not self.kiwoom.real_time_queue.empty():
                    data = self.kiwoom.real_time_queue.get()
                    code = data['code']
                    
                    # 데이터 업데이트
                    self.updateStockData(data)
                    
                    # 가격 상승 여부 확인
                    prev_price = self.kiwoom.stock_data[code].current_price
                    current_price = data['price']
                    self.kiwoom.stock_data[code].price_up = current_price > prev_price
                    
                    # 거래량 조건 체크
                    if self.kiwoom.stock_data[code].price_up:
                        self.checkVolumeConditions(code)
                        
                time.sleep(0.1)
            except Exception as e:
                logging.error(f"실시간 데이터 처리 오류: {str(e)}")

    def updateStockData(self, data):
        code = data['code']
        stock = self.kiwoom.stock_data[code]
        stock.current_price = data['price']
        stock.current_volume = data['volume']
        stock.change_rate = data['change_rate']
        stock.change_amount = data['change_amount']
        
        # 분봉 데이터 업데이트
        current_time = time.strftime("%H%M")
        if current_time[-2:] == "00":  # 매 분마다
            self.updateMinuteData(stock, time.strftime("%H%M%S"), data['volume'])

    def checkVolumeConditions(self, code):
        """거래량 조건 체크"""
        try:
             
            if code not in self.kiwoom.stock_data:
                return

            stock = self.kiwoom.stock_data[code]
            
            if len(stock.three_min_data) >= 3:
                # 직전 3개 3분봉 평균 거래량
                prev_volumes = [d['volume'] for d in stock.three_min_data[-3:]]
                avg_volume = sum(prev_volumes) / 3
                
                # 현재 3분봉 거래량
                current_volume = stock.current_volume
                
                # 거래량 증가 비율 계산
                if avg_volume > 0:
                    volume_ratio = current_volume / avg_volume
                    
                    # 조건 충족 시 테이블에 추가
                    if volume_ratio >= 3:
                        self.addToVolumeTable(self.volume_3x_table, stock)
                    elif volume_ratio >= 2:
                        self.addToVolumeTable(self.volume_2x_table, stock)
        
        except Exception as e:
            logging.error(f"거래량 조건 체크 실패: {str(e)}")

    def addToVolumeTable(self, table, stock):
        """거래량 테이블에 종목 추가"""
        try:
            row = table.rowCount()
            table.insertRow(row)
            
            items = [
                QTableWidgetItem(time.strftime("%H:%M:%S")),  # 발생시간
                QTableWidgetItem(""),  # 조건검색식 (빈 값)
                QTableWidgetItem(stock.code),  # 종목코드
                QTableWidgetItem(stock.name),  # 종목명
                QTableWidgetItem(str(stock.current_price)),  # 현재가
                QTableWidgetItem(f"{stock.change_rate}%"),  # 등락율
                QTableWidgetItem(str(stock.change_amount))  # 증감금액
            ]
            
            # 테이블 컬럼 수에 맞게 조정 (7개 컬럼)
            for col, item in enumerate(items):
                table.setItem(row, col, item)
            
        except Exception as e:
            logging.error(f"테이블 추가 실패: {str(e)}")

    def updateMinuteData(self, stock, current_time, volume):
        """분봉 데이터 업데이트"""
        try:
            # 새로운 분봉 시작
            if not stock.last_update_time or \
               current_time[:4] != stock.last_update_time[:4]:
                
                # 1분봉 데이터 추가
                stock.minute_data.append({
                    'time': current_time,
                    'volume': volume
                })
                if len(stock.minute_data) > 30:
                    stock.minute_data.pop(0)
                
                # 3분봉 데이터 업데이트
                if len(stock.minute_data) % 3 == 0:
                    three_min_volume = sum(d['volume'] for d in stock.minute_data[-3:])
                    stock.three_min_data.append({
                        'time': current_time,
                        'volume': three_min_volume
                    })
                    if len(stock.three_min_data) > 10:
                        stock.three_min_data.pop(0)
            
            stock.last_update_time = current_time
            
        except Exception as e:
            logging.error(f"분봉 데이터 업데이트 실패: {str(e)}")

    def stopTrace(self):
        """Trace 중단"""
        try:
            self.is_running = False
            
            # 실시간 조건검색 중단
            for i in range(self.trace_condition_list.count()):
                condition = self.trace_condition_list.item(i).text()
                condition_index = condition.split(':')[0]
                self.kiwoom.send_condition("0156", condition, int(condition_index), 0)
                
            # 실시간 데이터 수신 중단
            self.kiwoom.disconnect_real_data("0101")
            
            if self.processing_thread:
                self.processing_thread.join(timeout=1.0)
            
        except Exception as e:
            logging.error(f"Trace 중단 실패: {str(e)}")

    def showGroupStocks(self, item):
        """관심종목군 더블클릭시 종목 리스트에 추가"""
        try:
            code = item.text().split('-')[0].strip()
            name = self.kiwoom.get_master_code_name(code)
            if name:
                # 중복 체크
                new_item_text = f"{code} - {name}"
                for i in range(self.stock_list.count()):
                    if new_item_text == self.stock_list.item(i).text():
                        logging.info(f"이미 존재하는 종목입니다: {new_item_text}")
                        return
                
                # 중복이 아닌 경우에만 추가
                self.stock_list.addItem(new_item_text)
                logging.info(f"종목 추가됨: {new_item_text}")
                
        except Exception as e:
            logging.error(f"종목 리스트 표시 실패: {str(e)}")
            QMessageBox.critical(self, "오류", f"종목 추가 실패: {str(e)}")

    def addToTraceList(self, item):
        """종목 리스트에서 Trace 리스트로 추가"""
        try:
            # 중복 체크
            for i in range(self.trace_stock_list.count()):
                if item.text() == self.trace_stock_list.item(i).text():
                    return
            
            code = item.text().split('-')[0].strip()
            name = item.text().split('-')[1].strip()
            
            # 종목 데이터 초기화
            if self.is_running:
                self.initializeStockData(code, name)
            
            self.trace_stock_list.addItem(item.text())
            
        except Exception as e:
            logging.error(f"Trace 리스트 추가 실패: {str(e)}")

    def addToTraceCondition(self, item):
        """조건검색식을 Trace 조건검색식 리스트로 추가"""
        try:
            # 중복 체크
            for i in range(self.trace_condition_list.count()):
                if item.text() == self.trace_condition_list.item(i).text():
                    return
            
            self.trace_condition_list.addItem(item.text())
        except Exception as e:
            logging.error(f"Trace 조건검색식 추가 실패: {str(e)}")

    def process_real_time_data(self):
        """실시간 데이터 처리"""
        try:
            if not self.kiwoom.real_time_queue.empty():
                data = self.kiwoom.real_time_queue.get()
                code = data['code']
                
                if code in self.kiwoom.stock_data:
                    self.kiwoom.stock_data[code].update(data)
                    self.updateTables(code)
        except Exception as e:
            logging.error(f"실시간 데이터 처리 실패: {str(e)}")

    def updateTables(self, code):
        """테이블 업데이트"""
        try:
            data = self.kiwoom.stock_data[code]
            if data.price_up:
                self.checkVolumeConditions(code)
        except Exception as e:
            logging.error(f"테이블 업데이트 실패: {str(e)}")

    def toggleLogging(self):
        """로깅 시작/중지 토글"""
        try:
            if not self.is_logging:
                # 로깅 시작
                current_time = time.strftime("%Y%m%d%H")
                self.current_log_file = f"{current_time}.txt"
                self.is_logging = True
                self.logging_btn.setText("Trace 로깅 중지")
                
                # 로깅 시작 메시지
                with open(self.current_log_file, 'a', encoding='utf-8') as f:
                    f.write(f"=== 로깅 시작: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                
                QMessageBox.information(self, "알림", f"로깅이 시작되었습니다.\n파일: {self.current_log_file}")
            else:
                # 로깅 중지
                if self.current_log_file:
                    with open(self.current_log_file, 'a', encoding='utf-8') as f:
                        f.write(f"=== 로깅 종료: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                
                self.is_logging = False
                self.logging_btn.setText("Trace 로깅 시작")
                QMessageBox.information(self, "알림", "로깅이 중지되었습니다.")
                
        except Exception as e:
            logging.error(f"로깅 토글 실패: {str(e)}")
            QMessageBox.critical(self, "오류", f"로깅 처리 중 오류 발생: {str(e)}")

    def __del__(self):
        """종료 시 정리"""
        try:
            pythoncom.CoUninitialize()
        except:
            pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


