import logging
import ccxt
from datetime import datetime
from config import *
from utils import get_bollinger, exchange
#from app import get_cached_price

def calculate_target_price(currency, entry_price):
    """
    實現止盈策略的具體邏輯：
    - 各倉位以買入價格為基準，當價格漲幅 >= 2.5% 時自動賣出該倉位。
    """
    try:
        logging.info(f"開始計算 {currency} 的止盈價格，入場價格: {entry_price}")
        
        # 檢查入場價格是否有效
        if not entry_price or entry_price <= 0:
            logging.error(f"{currency} 入場價格無效: {entry_price}")
            return None
        
        # 計算止盈價格（漲幅 ≥ 2.5%）
        target_price = entry_price * 1.025  # 2.5% 漲幅
        logging.info(f"{currency} 的止盈價格設定為: {target_price:.4f}")
        
        return target_price
    
    except Exception as e:
        logging.error(f"{currency} 計算止盈價格時發生錯誤: {str(e)}")
        return None
   