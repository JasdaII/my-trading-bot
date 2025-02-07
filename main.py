import ccxt
import numpy as np
import time
import logging
from datetime import datetime, timedelta
from config import *
from utils import (
    exchange,
    get_bollinger
)
from strategies.entry_strategy import open_position
from strategies.exit_strategy import calculate_target_price


# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler()  # 同時輸出到控制台
    ]
)

# 檢查交易所是否初始化
if not exchange:
    logging.error("交易所未初始化，無法執行交易")
    raise RuntimeError("交易所未初始化")

def process_open_position(currency: str, current_price: float):
    """根據條件開倉"""
    try:
        # 檢查是否為首倉
        if len(trade_info[currency]['positions']) == 0:
            success, error_msg = open_position(currency, current_price, first_position_amount)
            if success:
                logging.info(f"{currency} 首倉建立成功")
            else:
                logging.info(f"{currency} 首倉建立失敗: {error_msg}")
            return
        
        # 檢查是否滿足跌幅條件（第 2-12 倉位）
        last_position = trade_info[currency]['positions'][-1]
        last_entry_price = last_position['entry_price']
        price_drop = (last_entry_price - current_price) / last_entry_price * 100
        
        if price_drop >= 6.0:
            success, error_msg = open_position(currency, current_price, first_position_amount)
            if success:
                logging.info(f"{currency} 新倉位建立成功，價格: {current_price:.4f}")
            else:
                logging.info(f"{currency} 新倉位建立失敗: {error_msg}")
        else:
            logging.info(f"{currency} 價格跌幅未達 6%，不建立新倉位")
    except Exception as e:
        logging.error(f"{currency} 處理開倉時發生錯誤: {str(e)}")

def process_manage_positions(currency: str, current_price: float):
    """管理現有倉位"""
    try:
        logging.info(f"開始管理 {currency} 倉位")
        positions = trade_info[currency]['positions']
        if not positions:
            logging.info(f" {currency} 無持倉")
            return
        
        logging.info(f" {currency} 當前持倉數量: {len(positions)}")
        
        for position in list(positions):  # 使用 list() 避免在迭代中修改列表
            try:
                
                # 計算止盈價格
                target_price = calculate_target_price(currency, position['entry_price'])
                             
                # 如果當前價格達到或超過止盈價格，則賣出該倉位
                if target_price and current_price >= target_price:
                    logging.info(f" {currency} 達到止盈價格: {target_price:.4f}")
                     # 賣出該倉位
                    amount = position.get('amount')                    
                    if amount:
                        order = exchange.create_market_sell_order(f"{currency}/USDT", amount)
                        if order:
                            logging.info(f" {currency} 成功賣出倉位")
                                                       
                            # 更新每日收益
                            profit = (current_price - position['entry_price']) * amount
                            trade_info[currency]['daily_profit'] += profit
                            
                            # 從持倉列表中移除該倉位
                            trade_info[currency]['positions'].remove(position)
                            save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件
                        else:
                            logging.error(f" {currency} 賣出倉位失敗")
                    else:
                        logging.error(f" {currency} amount not found in position")
                else:
                    logging.info(f" {currency} 當前價格未達到止盈價格: {current_price:.4f} < {target_price:.4f}")
            
            except ccxt.InsufficientFunds as e:
                logging.error(f" {currency} 餘額不足: {str(e)}")
            except ccxt.NetworkError as e:
                logging.error(f" {currency} 網路錯誤: {str(e)}")
            except Exception as e:
                logging.error(f" {currency} 管理持倉錯誤: {str(e)}")
    
    except Exception as e:
        logging.error(f" {currency} 管理倉位時發生錯誤: {str(e)}")


def trade_strategy():
    """執行交易策略"""
    if not exchange:
        logging.error("交易所未初始化，無法執行交易策略")
        return
    try:
        for currency in supported_currencies:
            # 使用最新價格
            ticker = exchange.fetch_ticker(f"{currency}/USDT")
            current_price = float(ticker['last'])
            if current_price is None:
                logging.warning(f"{currency} 無法獲取價格，跳過該貨幣")
                continue
            
            logging.info(f"正在處理 {currency}，當前價格: {current_price}")
            
            # 檢查是否正在等待開倉
            if trade_info[currency]['waiting_for_open']:
                # 立即檢查是否符合開倉條件
                bollinger = get_bollinger(f"{currency}/USDT", timeframe='1h', period=20, deviation=2)
                lower_band = bollinger['lower']  # 布林通道下軌價格
                if current_price <= lower_band:
                    success, error_msg = open_position(currency, current_price, first_position_amount)
                    if success:
                        logging.info(f" {currency} 首倉建立成功")
                        trade_info[currency]['waiting_for_open'] = False  # 建立首倉後，取消等待狀態
                    else:
                        logging.info(f" {currency} 首倉建立失敗: {error_msg}")
                        trade_info[currency]['waiting_for_open'] = False  # 建立首倉失敗，取消等待狀態
                else:
                    logging.info(f" {currency} 價格尚未觸及下軌，繼續等待")
                continue 
            
            if trade_info[currency]['is_trading'] and len(trade_info[currency]['positions']) < max_positions:
                process_open_position(currency, current_price) 
               
            if len(trade_info[currency]['positions']) > 0:
                process_manage_positions(currency, current_price)                 
              
             
            # 保存持倉數據到 JSON 文件
            save_trade_info_to_file(trade_info)
    except Exception as e:
        logging.error(f"交易策略執行錯誤: {str(e)}")

def manage_positions(currency, current_price):
    """管理持倉，檢查是否達到目標價格或止損價格"""
    try:
        logging.info(f"開始管理 {currency} 倉位")
        positions = trade_info[currency]['positions']
        
        if not positions:
            logging.info(f"{currency} 無持倉")
            return
            
        logging.info(f"{currency} 當前持倉數量: {len(positions)}")
        
        for position in positions:
            try:
                # 檢查是否達到目標價格
                target_price = calculate_target_price(currency, position['entry_price'])
                if target_price and current_price >= target_price:
                    logging.info(f"{currency} 達到目標價格: {target_price}")
                    
                    # 將該持倉移除
                    trade_info[currency]['positions'].remove(position)
                    
                    # 更新每日收益
                    trade_info[currency]['daily_profit'] += position['profit']
                    
            except Exception as e:
                logging.error(f"管理持倉錯誤: {str(e)}")
                
    except Exception as e:
        logging.error(f"管理持倉錯誤: {str(e)}")

#def main():
    """主程序，定期執行交易策略和更新統計資料"""
    #while True:
       # try:
            # 執行交易策略
           # trade_strategy()   
            # 保存持倉數據到 JSON 文件
           # save_trade_info_to_file(trade_info)
            # 等待60秒後再次執行
           # time.sleep(60)
      #  except Exception as e:
           # logging.error(f"主程序錯誤: {str(e)}")
           # time.sleep(60)

#if __name__ == "__main__":
   # main()