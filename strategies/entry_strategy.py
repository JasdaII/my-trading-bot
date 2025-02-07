import logging
import ccxt
import time
import numpy as np
from datetime import datetime
from config import *
from utils import exchange,get_bollinger,calculate_volatility
from strategies.exit_strategy import calculate_target_price


def open_position(currency, price, amount=30):
    """
    實現建倉策略的具體邏輯
    - 首倉：價格跌破或觸及布林通道下軌。
    - 第 2-12 倉位：價格相對於前一倉位入場價格跌幅 ≥ 6%。
    """
    try:       
        # 檢查交易所連接
        if not exchange:
            error_msg = f"{currency} 開倉失敗: 交易所未連接"
            logging.error(error_msg)
            return False, error_msg
        
        # 檢查是否超過最大倉位數
        if len(trade_info[currency]['positions']) >= max_positions:
            error_msg = f"{currency} 已達到最大倉位數 {max_positions}"
            logging.info(error_msg)
            return False, error_msg
        
        # 檢查總投資額是否超過限制
        total_investment = sum([
            sum([p['amount'] * p['entry_price'] for p in info['positions']])
            for info in trade_info.values()
        ])
        if total_investment + amount > total_investment_limit:
            error_msg = f"總投資額 {total_investment + amount} 超過限制 {total_investment_limit}"
            logging.info(error_msg)
            return False, error_msg
        
        # 檢查餘額是否足夠
        try:
            balance = exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            if usdt_balance < amount:
                error_msg = f"{currency} 餘額不足: 需要 {amount} USDT，當前餘額 {usdt_balance} USDT"
                logging.warning(error_msg)
                return False, error_msg
        except Exception as e:
            error_msg = f"{currency} 檢查餘額失敗: {str(e)}"
            logging.error(error_msg)
            return False, error_msg
        
        # 獲取布林通道數據（1小時區間框架）
        bollinger = get_bollinger(f"{currency}/USDT", timeframe='1h', period=20, deviation=2)
        if not bollinger:
            error_msg = f"{currency} 無法獲取布林通道數據"
            logging.error(error_msg)
            return False, error_msg
        
        lower_band = bollinger['lower']  # 布林通道下軌
        current_price = price  # 當前價格
        
        # 檢查是否為首倉
        if len(trade_info[currency]['positions']) == 0:
            # 首倉建倉條件：價格跌破或觸及布林通道下軌
            if current_price <= lower_band:
                entry_amount = amount / current_price
                order = exchange.create_market_buy_order(f"{currency}/USDT", entry_amount)
                trade_info[currency]['positions'].append({
                    'entry_price': current_price,
                    'amount': entry_amount,
                    'target_price': calculate_target_price(currency, current_price),  # 計算止盈價格
                    'profit': 0,
                    'timestamp': datetime.now().timestamp() * 1000  # 設置當前時間戳
                })
                if order:
                   save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件
                   logging.info(f"{currency} 首倉建立成功，價格: {current_price:.4f}")
                else:
                   logging.error(f"{currency} 首倉建立失敗")  
            else:
                logging.info(f"{currency} 價格未跌破布林通道下軌，等待開倉條件")
                return False, "等待開倉條件"
        else:
             # 第 2-12 倉位建倉條件：價格跌幅 ≥ 6%
            last_position = trade_info[currency]['positions'][-1]
            last_entry_price = last_position['entry_price']
            price_drop = (last_entry_price - current_price) / last_entry_price * 100

                     
            # 根據貨幣的歷史波動率動態調整跌幅條件
            #volatility = calculate_volatility(currency)
            #dynamic_drop_threshold = max(6.0, volatility * 100)  # 最小跌幅為 6%
            #if price_drop >= dynamic_drop_threshold:
            
            if price_drop >= 6.0:
                entry_amount = amount / current_price
                order = exchange.create_market_buy_order(f"{currency}/USDT", entry_amount)
                trade_info[currency]['positions'].append({
                    'entry_price': current_price,
                    'amount': entry_amount,
                    'target_price': calculate_target_price(currency, current_price),  # 計算止盈價格
                    'profit': 0,
                    'timestamp': datetime.now().timestamp() * 1000  # 設置當前時間戳
                })
                if order:
                   save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件
                   logging.info(f"{currency} 新倉位建立成功，價格: {current_price:.4f}")
                   return True,None
                else:
                   logging.error(f"{currency} 新倉位建立失敗")
               
                
            else:
                logging.info(f"{currency} 價格跌幅未達 6%，不建立新倉位")
                return False, "價格跌幅未達 6%"
    except Exception as e:
        error_msg = f"{currency} 開倉操作錯誤: {str(e)}"
        logging.error(error_msg)
        return False, error_msg