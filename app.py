import os
import sys
import ccxt
import logging
import threading
import time
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from config import *
from utils import exchange
from strategies.entry_strategy import open_position
from utils import get_bollinger  # 新增這一行
from main import trade_strategy


# 確保日誌目錄存在
if not os.path.exists('logs'):
    os.makedirs('logs')

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/trading.log', mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# 設置 Flask 的日誌
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
for handler in logging.getLogger().handlers:
    app.logger.addHandler(handler)

# 初始化時的日誌
logging.info("="*50)
logging.info("交易系統啟動")
logging.info(f"支援的貨幣: {', '.join(supported_currencies)}")
logging.info("="*50)

# 緩存變量
cached_trade_info = None
cache_expiry_time = None
CACHE_DURATION = timedelta(seconds=60)  # 緩存有效期為60秒

def get_trade_info():
    """獲取最新的交易資訊，使用緩存機制降低請求頻率"""
    global cached_trade_info, cache_expiry_time
    # 如果緩存未過期，直接返回緩存的數據
    if cached_trade_info and datetime.now() < cache_expiry_time:
        logging.info("使用緩存的交易資訊")
        return cached_trade_info['trade_info'], cached_trade_info['usdt_balance']
    
    try:
        if not exchange:
            logging.error("交易所未初始化")
            return trade_info, 0.0
        
        total_investment = 0.0
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        # 獲取交易所的持倉數據
        try:
            balance = exchange.fetch_balance()
            usdt_balance = float(balance.get('USDT', {}).get('free', 0))
            logging.info(f"USDT餘額: {usdt_balance}")
        except Exception as e:
            logging.error(f"獲取餘額失敗: {str(e)}")
            usdt_balance = 0.0
        
        for currency in supported_currencies:
            try:
                # 獲取當前價格（使用緩存機制）
                ticker = exchange.fetch_ticker(f"{currency}/USDT")
                price =  float(ticker['last']) 
                if price is None:
                    logging.error(f"無法獲取 {currency} 的價格，跳過該貨幣")
                    continue
                
                trade_info[currency]['current_price'] = price
                
                # 初始化每日和每月收益
                if 'daily_profit' not in trade_info[currency]:
                    trade_info[currency]['daily_profit'] = 0.0
                if 'monthly_profit' not in trade_info[currency]:
                    trade_info[currency]['monthly_profit'] = 0.0
                
                # 獲取該幣種的持倉數量
                currency_balance = float(balance.get(currency, {}).get('free', 0))
                
                # 更新持倉數據
                if currency_balance > 0:
                    if not trade_info[currency]['positions']:
                        # 如果沒有持倉數據，則新增初始倉位
                        position = {
                            'amount': currency_balance,
                            'entry_price': price,  # 記錄開倉時的價格
                            'target_price':price * 1.025,
                            'timestamp': datetime.now().timestamp() * 1000,  # 時間戳
                            'current_value': currency_balance * price,
                            'profit': 0.0  # 初始收益為 0
                        }
                        trade_info[currency]['positions'].append(position)
                    else:
                        # 如果已有持倉，檢查是否需要更新其他字段
                        for position in trade_info[currency]['positions']:
                            position['current_value'] = float(position['amount']) * price
                            position['profit'] = position['current_value'] - (float(position['amount']) * float(position['entry_price']))
                
                # 更新 is_trading 狀態
                if len(trade_info[currency]['positions']) > 0:
                    trade_info[currency]['is_trading'] = True  # 如果有持倉，則設置為正在交易
                else:
                    trade_info[currency]['is_trading'] = False  # 如果沒有持倉，則設置為未交易
                
                # 計算該幣種的總投資額
                currency_investment = sum(
                    float(position['amount']) * float(position['entry_price'])
                    for position in trade_info[currency]['positions']
                )
                total_investment += currency_investment
                
                # 計算每日收益
                daily_profit = sum(
                    position['profit']
                    for position in trade_info[currency]['positions']
                    if isinstance(position['timestamp'], (int, float)) and
                       datetime.fromtimestamp(position['timestamp'] / 1000).strftime('%Y-%m-%d') == today
                )
                trade_info[currency]['daily_profit'] = daily_profit
                
                # 計算每月收益（簡化邏輯）
                trade_info[currency]['monthly_profit'] = sum(p['profit'] for p in trade_info[currency]['positions'])
                
                logging.info(f"{currency} 投资额: {currency_investment:.2f} USDT, 当日收益: {daily_profit:.2f}")
            
            except Exception as e:
                logging.error(f"更新 {currency} 資訊時出錯: {str(e)}")
                continue
        
        logging.info(f"總投資額: {total_investment:.2f} USDT")
        
        # 保存持倉數據到 JSON 文件
        save_trade_info_to_file(trade_info)
        
        # 更新緩存
        cached_trade_info = {
            'trade_info': trade_info,
            'usdt_balance': usdt_balance,
            'total_investment': total_investment
        }
        cache_expiry_time = datetime.now() + CACHE_DURATION
        
        return trade_info, usdt_balance
    
    except Exception as e:
        logging.error(f"獲取交易資訊時出錯: {str(e)}")
        return trade_info, 0.0
    
# 定義根路徑
@app.route('/')
def index():
    try:
        current_trade_info, usdt_balance = get_trade_info()
        total_asset_value = usdt_balance  # 從可用 USDT 餘額開始

        # 計算總資產價值
        for currency, info in current_trade_info.items():
            try:
                ticker = exchange.fetch_ticker(f"{currency}/USDT")
                current_price = float(ticker['last'])
                for position in info['positions']:
                    if isinstance(position, dict) and 'amount' in position:
                        position_value = float(position['amount']) * current_price
                        total_asset_value += position_value
            except Exception as e:
                logging.error(f"獲取 {currency} 價格失敗: {e}")

        # 計算每日、每月收益和年化收益率
        daily_profit = sum(info.get('daily_profit', 0) for info in current_trade_info.values())
        monthly_profit = sum(info.get('monthly_profit', 0) for info in current_trade_info.values())
        days_passed = (datetime.now() - datetime(datetime.now().year, 1, 1)).days
        annual_return = (daily_profit / total_asset_value * 365 / days_passed * 100) if total_asset_value > 0 else 0

        # 計算總收益（從第一次交易開始累積）
        total_profit = sum(info.get('total_profit', 0) for info in current_trade_info.values())

        logging.info(f"渲染首頁 - 總資產: {total_asset_value:.2f} USDT")

        return render_template('index.html',
                             trade_info=current_trade_info,
                             total_investment=total_asset_value, # 使用新的總資產價值
                             total_profit=total_profit,         # 新增總收益
                             annual_return=annual_return,
                             usdt_balance=usdt_balance,
                             daily_profit=daily_profit,
                             monthly_profit=monthly_profit,
                             max_positions=max_positions)

    except Exception as e:
        error_msg = f"首頁載入錯誤: {str(e)}"
        logging.error(error_msg)
        return render_template('index.html',
                             trade_info=initialize_trade_info(),
                             total_investment=0,
                             total_profit=0,  # 新增總收益
                             annual_return=0,
                             usdt_balance=0,
                             daily_profit=0,
                             monthly_profit=0,
                             max_positions=max_positions,
                             error_message=error_msg)

# 定義倉位管理頁面路由
@app.route('/manage_positions/<currency>')
def manage_positions(currency):
    try:
        # 獲取當前交易資訊
        current_trade_info, _ = get_trade_info()
        # 檢查該幣種是否存在於交易資訊中
        if currency not in current_trade_info:
            return render_template('error.html', error_message=f"貨幣 {currency} 未找到"), 404
        
        # 獲取該幣種的持倉資訊
        positions = current_trade_info[currency]['positions']
        
        # 確保每個持倉都有必要的鍵
        for position in positions:
            if 'target_price' not in position or position['target_price'] is None:
                position['target_price'] = 0.0  # 使用字符串表示未計算
            else: 
                position['target_price'] = float(position['entry_price'])*1.025
            if 'profit' not in position:
                position['profit'] = 0.0
            if 'amount' not in position:
                position['amount'] = 0.0
        
        # 計算總持倉和總收益
        total_amount = sum(position.get('amount', 0) for position in positions)
        total_profit = sum(position.get('profit', 0) for position in positions)
        
        # 渲染倉位管理頁面
        return render_template('manage_positions.html', 
                               currency=currency, 
                               positions=positions,
                               total_amount=total_amount, 
                               total_profit=total_profit,
                               trade_info=current_trade_info)
    except Exception as e:
        error_msg = f"倉位管理頁面載入錯誤: {str(e)}"
        logging.error(error_msg)
        return render_template('error.html', error_message=error_msg), 500

@app.route('/api/close_all_positions/<currency>', methods=['POST'])
def close_all_positions(currency):
    try:
        # 獲取當前交易資訊
        current_trade_info, _ = get_trade_info()
        
        # 檢查該幣種是否存在於交易資訊中
        if currency not in current_trade_info:
            return jsonify({'success': False, 'error': f"貨幣 {currency} 未找到"}), 404
        
        # 獲取該幣種的所有倉位
        positions = current_trade_info[currency]['positions']
        
        # 檢查持倉數據是否為空
        if not positions:
            logging.error(f"{currency} 無持倉可賣出")
            return jsonify({'success': False, 'error': f"{currency} 無持倉可賣出"}), 400
        
        # 計算總持倉量
        total_amount = sum(position.get('amount', 0) for position in positions)
        
        # 檢查市場深度
        try:
            orderbook = exchange.fetch_order_book(f"{currency}/USDT")
            best_bid = orderbook['bids'][0][0] if orderbook['bids'] else 0
            best_ask = orderbook['asks'][0][0] if orderbook['asks'] else float('inf')

            if best_ask - best_bid > 0.01 * best_bid:  # 如果買賣差價超過 1%
                logging.warning(f"{currency} 買賣差價過大，跳過本次交易")
                return jsonify({'success': False, 'error': f"{currency} 買賣差價過大"}), 400
        except Exception as e:
            logging.error(f"{currency} 檢查市場深度失敗: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
        
        # 檢查最小交易數量
        try:
            markets = exchange.load_markets()
            market = markets.get(f"{currency}/USDT")
            if market and total_amount < market['limits']['amount']['min']:
                logging.warning(f"{currency} 交易量 {total_amount} 小於最小交易量 {market['limits']['amount']['min']}")
                # 如果剩餘數量小於最小交易量，直接清空持倉並結束交易狀態
                current_trade_info[currency]['positions'] = []
                current_trade_info[currency]['is_trading'] = False
                return jsonify({'success': True, 'message': f"{currency} 剩餘數量小於最小交易量，已清空持倉"})
        except Exception as e:
            logging.error(f"{currency} 檢查最小交易量失敗: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
        
        # 賣出所有倉位
        try:
            order = exchange.create_market_sell_order(f"{currency}/USDT", total_amount)
            logging.info(f"{currency} 所有倉位已賣出: {order}")
            
            # 清空該幣種的持倉數據
            current_trade_info[currency]['positions'] = []
            current_trade_info[currency]['is_trading'] = False  # 結束交易狀態

            save_trade_info_to_file(current_trade_info)  # 儲存到 JSON 文件
            
            return jsonify({'success': True})
        
        except ccxt.InsufficientFunds as e:
            logging.error(f"{currency} 餘額不足: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
        except ccxt.NetworkError as e:
            logging.error(f"{currency} 網路錯誤: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
        except ccxt.ExchangeError as e:
            logging.error(f"{currency} 交易所錯誤: {str(e)}")
            # 如果賣出失敗，檢查是否是因為剩餘數量小於最小交易量
            if "Order amount should be greater than the minimum available amount" in str(e):
                # 獲取當前價格
                ticker = exchange.fetch_ticker(f"{currency}/USDT")
                current_price = float(ticker['last'])
                
                # 計算剩餘單位數的價值
                remaining_value = total_amount * current_price
                
                # 如果剩餘單位數的價值小於 0.05 USDT，則清空持倉並結束交易狀態
                if remaining_value < 0.05:
                    current_trade_info[currency]['positions'] = []
                    current_trade_info[currency]['is_trading'] = False
                    save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件
                    return jsonify({'success': True, 'message': f"{currency} 剩餘數量價值小於 0.05 USDT，已清空持倉"})
                else:
                    return jsonify({'success': False, 'error': f"{currency} 剩餘數量價值大於 0.05 USDT，無法清空持倉"})
            return jsonify({'success': False, 'error': str(e)}), 500
        except Exception as e:
            logging.error(f"{currency} 賣出所有倉位失敗: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    except Exception as e:
        error_msg = f"關閉所有倉位錯誤: {str(e)}"
        logging.error(error_msg)
        return jsonify({'success': False, 'error': error_msg}), 500

@app.route('/start_trading/<currency>', methods=['POST'])
def start_trading(currency):
    try:
        if currency not in trade_info:
            error_msg = f"貨幣 {currency} 未找到"
            logging.error(error_msg)
            return jsonify({'success': False, 'error': error_msg}), 404
        
        # 獲取布林通道下軌價格
        bollinger = get_bollinger(f"{currency}/USDT", timeframe='1h', period=20, deviation=2)
        if not bollinger:
            error_msg = f"無法獲取 {currency} 的布林通道數據"
            logging.error(error_msg)
            return jsonify({'success': False, 'error': error_msg}), 500
        
        lower_band = bollinger['lower']  # 布林通道下軌價格
        
        # 設置等待開倉狀態
        trade_info[currency]['waiting_for_open'] = True
        trade_info[currency]['is_trading'] = True
        save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件

         # 嘗試立即開倉
        ticker = exchange.fetch_ticker(f"{currency}/USDT")
        price =  float(ticker['last']) 
        if price <= lower_band:
             current_price = price
             success, error_msg = open_position(currency, current_price, first_position_amount)
             if success:
                  logging.info(f" {currency} 開始交易，並立即開倉成功")
                  trade_info[currency]['waiting_for_open'] = False
                  save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件
                  return jsonify({
                        'success': True,
                        'message': f"開始交易成功，並立即開倉。當前價格: {current_price:.4f}，布林通道下軌價格: {lower_band:.4f} USDT"
                  })
             else:
                  logging.info(f" {currency} 開始交易，但無法立即開倉: {error_msg}")
                  return jsonify({
                        'success': True,
                        'message': f"開始交易成功，等待合適的開倉條件。當前價格: {current_price:.4f}，布林通道下軌價格: {lower_band:.4f} USDT"
                 })

        logging.info(f" {currency} 開始交易，等待合適的開倉條件")
        return jsonify({
            'success': True,
            'message': f" {currency} 開始交易，等待合適的開倉條件。當前布林通道下軌價格: {lower_band:.4f} USDT"
        })
         
    except Exception as e:
        error_msg = f"開始交易 {currency} 時出錯: {str(e)}"
        logging.error(error_msg)
        return jsonify({'success': False, 'error': error_msg}), 500
    
# 定義 API 接口
@app.route('/api/dashboard')
def api_dashboard():
    """API 接口：返回儀表板數據"""
    try:
        current_trade_info, usdt_balance = get_trade_info()
        total_asset_value = usdt_balance
        #trade_strategy()  # 調用 main.py 的核心邏輯

        # 計算總資產價值
        for currency, info in current_trade_info.items():
            try:
                ticker = exchange.fetch_ticker(f"{currency}/USDT")
                current_price = float(ticker['last'])
                for position in info['positions']:
                    if isinstance(position, dict) and 'amount' in position:
                        position_value = float(position['amount']) * current_price
                        total_asset_value += position_value
            except Exception as e:
                logging.error(f"獲取 {currency} 價格失敗: {e}")

        # 計算每日、每月收益和年化收益率
        daily_profit = sum(info.get('daily_profit', 0) for info in current_trade_info.values())
        monthly_profit = sum(info.get('monthly_profit', 0) for info in current_trade_info.values())
        days_passed = (datetime.now() - datetime(datetime.now().year, 1, 1)).days
        annual_return = (daily_profit / total_asset_value * 365 / days_passed * 100) if total_asset_value > 0 else 0

        # 按等待交易中和交易狀態排序
        sorted_trade_info = dict(sorted(current_trade_info.items(), key=lambda x: (
            -x[1].get('waiting_for_open', False),  # 等待交易中的優先
            -x[1].get('is_trading', False)        # 正在交易的次之
        )))
        save_trade_info_to_file(sorted_trade_info)  # 儲存到 JSON 文件
        # 返回 JSON 格式的數據
        return jsonify({
            'success': True,
            'trade_info': sorted_trade_info,
            'total_investment': total_asset_value,
            'usdt_balance': usdt_balance,
            'daily_profit': daily_profit,
            'monthly_profit': monthly_profit,
            'annual_return': annual_return
        })
    
    except Exception as e:
        logging.error(f"獲取儀表板數據時出錯: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def run_trade_strategy():
    while True:
        try:
            trade_strategy()            
            # 保存持倉數據到 JSON 文件
            save_trade_info_to_file(trade_info)
            time.sleep(60)
        except Exception as e:
            logging.error(f"交易策略執行錯誤: {str(e)}")
            time.sleep(60)

# 在 Flask 啟動時啟動後台線程
#@app.before_first_request FLASK 2.3.0以前版本
def start_background_tasks():
    print("啟動後台任務...")
    thread = threading.Thread(target=run_trade_strategy, daemon=True)
    thread.start()

# 啟動 Flask 開發服務器
if __name__ == '__main__':
     # 在應用程序啟動時啟動後台任務
    start_background_tasks()
    app.run(debug=True, host='0.0.0.0', port=5000)