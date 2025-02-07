import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# 載入環境變量
load_dotenv()

# API設置
okx_api_key = os.getenv('OKX_API_KEY')
okx_secret_key = os.getenv('OKX_SECRET_KEY')
okx_passphrase = os.getenv('OKX_PASSPHRASE')

# 驗證API憑證是否存在
if not all([okx_api_key, okx_secret_key, okx_passphrase]):
    logging.error("缺少必要的API憑證")
    raise ValueError("缺少必要的API憑證，請檢查.env文件")

# 交易參數設置
supported_currencies = [
'BTC', 'ETH', 'ADA', 'DOGE', 'DOT', 'UNI', 'ARB', 'KSM', 'SUI', 'SOL', 'AVAX', 'LINK', 'CRV']
max_positions = 12
total_investment_limit = 3000
first_position_amount = 30  # 首倉固定買入金額

# config.py
cached_prices = {}  # 全局變量，用於存儲緩存價格

# 技術指標參數
indicator_params = {
    'rsi': {
        'overbought': 70,
        'oversold': 30,
        'period': 14
    },
    'macd': {
        'fast': 12,
        'slow': 26,
        'signal': 9
    },
    'bollinger': {
        'period': 20,
        'deviation': 2
    }
}

# 套利回補機制參數
rebalance_params = {
    'min_positions': 5,  # 最少需要的倉位數量
    'min_profit': 2.5,  # 最小獲利比例 (0.5%)
    'sell_ratio_range': (0.05, 0.1),  # 賣出比例範圍 (5-10%)
    'min_amount': 0.0001,  # 最小交易數量
    'profit_share': 0.5  # 用於補充虧損的收益比例 (50%)
}

# 系統設置
SYSTEM_CONFIG = {
    'update_interval': 60,  # 數據更新間隔（秒）
    'max_retries': 5,      # API調用最大重試次數
    'retry_delay': 1,      # 重試延遲（秒）
    'log_level': logging.INFO,
    'debug_mode': True   # 調試模式開關
}

# 日誌設置
LOG_CONFIG = {
    'filename': 'logs/trading.log',
    'format': '%(asctime)s - %(levelname)s - %(message)s',
    'level': logging.INFO
}

def initialize_trade_info():
    return {currency: {
        'positions': [],
        'total_profit': 0.0,
        'daily_profit': 0.0,
        'monthly_profit': 0.0,
        'current_price': 0.0,
        'rebalance_history': [],
        'last_rebalance_time': None,
        'rebalance_count': 0,
        'is_trading': False,  # 是否正在交易
        'waiting_for_open': False  # 是否在等待開倉
    } for currency in supported_currencies}

# 定義 JSON 文件路徑
TRADE_INFO_FILE = 'trade_info.json'

def save_trade_info_to_file(trade_info):
    try:
        with open(TRADE_INFO_FILE, 'w', encoding='utf-8') as f:
            data_to_save = {
                currency: {
                    'positions': [
                        {
                            'entry_price': float_safe(position.get('entry_price', 0)),
                            'amount': float_safe(position.get('amount', 0)),
                            'target_price': float_safe(position.get('target_price', 0)),
                            'profit': float_safe(position.get('profit', 0)),
                            'timestamp': position.get('timestamp', datetime.now().timestamp() * 1000)  # 設置默認值
                        }
                        for position in info['positions']
                    ],
                    'total_profit': float_safe(info.get('total_profit', 0)),
                    'daily_profit': float_safe(info.get('daily_profit', 0)),
                    'monthly_profit': float_safe(info.get('monthly_profit', 0)),
                    'rebalance_history': info.get('rebalance_history', []),
                    'last_rebalance_time': info.get('last_rebalance_time', None),
                    'rebalance_count': info.get('rebalance_count', 0),
                    'is_trading': info.get('is_trading', False),
                    'waiting_for_open': info.get('waiting_for_open', False)
                }
                for currency, info in trade_info.items()
            }
            json.dump(data_to_save, f, ensure_ascii=False, indent=4, default=str)
        logging.info("持倉數據已成功保存到 JSON 文件")
    except Exception as e:
        logging.error(f"保存持倉數據到 JSON 文件失敗: {str(e)}")

def load_trade_info_from_file():
    try:
        if os.path.exists(TRADE_INFO_FILE):
            with open(TRADE_INFO_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                trade_info = initialize_trade_info()
                for currency, info in loaded_data.items():
                    if currency in trade_info:
                        trade_info[currency]['positions'] = [
                            {
                                'entry_price':float_safe(position.get('entry_price', 0)),
                                'amount': float_safe(position.get('amount', 0)),
                                'target_price': float_safe(position.get('target_price', 0)),
                                'profit': float_safe(position.get('profit', 0)),
                                'timestamp': position.get('timestamp', datetime.now().timestamp() * 1000)  # 設置默認值
                            }
                            for position in info.get('positions', [])
                        ]
                        trade_info[currency]['total_profit'] = float_safe(info.get('total_profit', 0))
                        trade_info[currency]['daily_profit'] = float_safe(info.get('daily_profit', 0))
                        trade_info[currency]['monthly_profit'] = float_safe(info.get('monthly_profit', 0))
                        trade_info[currency]['rebalance_history'] = info.get('rebalance_history', [])
                        trade_info[currency]['last_rebalance_time'] = info.get('last_rebalance_time', None)
                        trade_info[currency]['rebalance_count'] = info.get('rebalance_count', 0)
                        trade_info[currency]['is_trading'] = info.get('is_trading', False)
                        trade_info[currency]['waiting_for_open'] = info.get('waiting_for_open', False)
                logging.info("持倉數據已成功從 JSON 文件加載")
                return trade_info
        else:
            logging.warning("JSON 文件不存在，初始化新的 trade_info")
            return initialize_trade_info()
    except Exception as e:
        logging.error(f"從 JSON 文件加載持倉數據失敗: {str(e)}")
        return initialize_trade_info()

def float_safe(value):
    """安全地將值轉換為浮點數，如果無法轉換則返回默認值"""
    try:
        return float(value or 0)  # 如果值為空或無效，返回 0
    except (ValueError, TypeError):
        return 0.0
    
# 初始化交易信息
#trade_info = initialize_trade_info()
trade_info = load_trade_info_from_file()