def startTrace(self):
    if not self.kiwoom.connected:
        QMessageBox.warning(self, "경고", "로그인이 필요합니다.")
        return

    try:
        self.is_running = True
        
        # 화면번호 관리를 위한 기본값 설정
        base_screen_no = 5000  # 기준 화면번호
        
        # 조건검색식 실시간 감시 시작
        for i in range(self.trace_condition_list.count()):
            condition_item = self.trace_condition_list.item(i).text()
            condition_index, condition_name = condition_item.split(':', 1)
            
            try:
                condition_index = int(condition_index)
                if condition_index < 0:
                    continue
                    
                # 조건검색용 화면번호 할당
                screen_no = str(base_screen_no + i)
                ret = self.kiwoom.send_condition(screen_no, condition_name, condition_index, 1)
                
                if ret == 1:
                    logging.info(f"조건검색 시작 성공: {condition_name}")
                else:
                    logging.error(f"조건검색 시작 실패: {condition_name}")
                    
                # 요청 간격 조절
                time.sleep(0.5)
                
            except ValueError:
                logging.error(f"유효하지 않은 조건식 인덱스: {condition_index}")
                continue
        
        # Trace 종목 실시간 데이터 수신 시작
        for i in range(self.trace_stock_list.count()):
            code = self.trace_stock_list.item(i).text().split('-')[0].strip()
            
            # 종목별 화면번호 할당 (기존 화면번호와 겹치지 않게)
            stock_screen_no = str(6000 + i)
            
            # 이전 데이터 정리
            if code in self.kiwoom.stock_data:
                self.kiwoom.disconnect_real_data(stock_screen_no)
                
            # 종목 초기화 및 실시간 등록
            self.initializeStockData(code)
            self.kiwoom.set_real_reg(stock_screen_no, code, "10;11;12;15;20", "0")
            
            # 요청 간격 조절
            time.sleep(0.35)  # 요청 간격을 좀 더 보수적으로 설정
        
        # 실시간 데이터 처리 스레드 시작 전 메모리 정리
        self.cleanup_memory()
        
        # 실시간 데이터 처리 스레드 시작
        self.processing_thread = threading.Thread(target=self.processRealTimeData)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        
    except Exception as e:
        logging.error(f"Trace 시작 실패: {str(e)}")
        self.is_running = False

def processRealTimeData(self):
    """실시간 데이터 처리 메인 로직"""
    cleanup_counter = 0  # 정리 주기 카운터
    
    while self.is_running:
        try:
            cleanup_counter += 1
            
            # 100회 처리마다 메모리 정리 수행
            if cleanup_counter >= 100:
                self.cleanup_memory()
                cleanup_counter = 0
            
            if not self.kiwoom.real_time_queue.empty():
                # 큐가 너무 많이 쌓이면 일부 스킵
                if self.kiwoom.real_time_queue.qsize() > 100:
                    for _ in range(self.kiwoom.real_time_queue.qsize() - 50):
                        try:
                            self.kiwoom.real_time_queue.get_nowait()
                        except Queue.Empty:
                            break
                
                data = self.kiwoom.real_time_queue.get()
                code = data['code']
                
                # 데이터 업데이트
                if code in self.kiwoom.stock_data:
                    self.updateStockData(data)
                    
                    # 가격 상승 여부 확인
                    prev_price = self.kiwoom.stock_data[code].current_price
                    current_price = data['price']
                    price_up = current_price > prev_price
                    
                    # 가격 상승 시에만 거래량 체크
                    if price_up:
                        self.checkVolumeConditions(code)
            
            # CPU 부하 감소를 위한 대기
            time.sleep(0.1)
            
        except Exception as e:
            logging.error(f"실시간 데이터 처리 오류: {str(e)}")
            time.sleep(1)  # 에러 발생 시 잠시 대기

def cleanup_memory(self):
    """메모리 정리 함수"""
    try:
        current_time = time.time()
        codes_to_remove = []
        
        # 오래된 데이터 정리
        for code, stock_data in self.kiwoom.stock_data.items():
            if hasattr(stock_data, 'last_update_time'):
                # 10분 이상 업데이트 없는 데이터 제거
                if current_time - stock_data.last_update_time > 600:
                    codes_to_remove.append(code)
        
        # 데이터 제거
        for code in codes_to_remove:
            del self.kiwoom.stock_data[code]
            
        # 큐 정리
        while not self.kiwoom.real_time_queue.empty():
            try:
                self.kiwoom.real_time_queue.get_nowait()
            except Queue.Empty:
                break
                
        # 가비지 컬렉션 강제 실행
        gc.collect()
        
    except Exception as e:
        logging.error(f"메모리 정리 실패: {str(e)}")

def stopTrace(self):
    """Trace 중단"""
    try:
        self.is_running = False
        
        # 실시간 조건검색 중단
        for i in range(self.trace_condition_list.count()):
            condition = self.trace_condition_list.item(i).text()
            condition_index = condition.split(':')[0]
            screen_no = str(5000 + i)
            self.kiwoom.send_condition(screen_no, condition, int(condition_index), 0)
            
        # 실시간 데이터 수신 중단 (종목별)
        for i in range(self.trace_stock_list.count()):
            screen_no = str(6000 + i)
            self.kiwoom.disconnect_real_data(screen_no)
        
        # 스레드 종료 대기
        if self.processing_thread:
            self.processing_thread.join(timeout=1.0)
            
        # 메모리 정리
        self.cleanup_memory()
        
    except Exception as e:
        logging.error(f"Trace 중단 실패: {str(e)}")