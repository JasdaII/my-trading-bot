import logging
import numpy as np
import ccxt
from datetime import datetime
from config import *
from utils import exchange

def rebalance_positions(currency):
    """
    實現回補機制的具體邏輯
    
    Args:
        currency (str): 貨幣代碼
    
    Returns:
        bool: 再平衡是否成功
    """
    try:
        if not exchange:
            logging.error(f"{currency} 再平衡失敗: 交易所未初始化")
            return False
            
        positions = trade_info[currency]['positions']
        if len(positions) < rebalance_params['min_positions']:
            logging.info(f"{currency} 持倉數量不足{rebalance_params['min_positions']}個，無需再平衡")
            return False
            
        logging.info(f"開始{currency}倉位再平衡")
        rebalance_success = False
        
        # 從第5個倉位開始賣出
        for i in range(rebalance_params['min_positions']-1, len(positions)):
            position = positions[i]
            
            try:
                if not isinstance(position['profit'], (int, float)) or np.isnan(position['profit']):
                    logging.warning(f"{currency} 倉位 {i} 收益計算錯誤，跳過該倉位")
                    continue
                    
                profit_percentage = (position['profit'] / (position['amount'] * position['entry_price'])) * 100
                if profit_percentage <= rebalance_params['min_profit']:
                    logging.info(f"{currency} 倉位 {i} 獲利{profit_percentage:.2f}%不足{rebalance_params['min_profit']}%，跳過該倉位")
                    continue
                    
                if not isinstance(position['amount'], (int, float)) or position['amount'] <= 0:
                    logging.warning(f"{currency} 倉位 {i} 持倉量異常，跳過該倉位")
                    continue
                
                # 使用配置的賣出比例範圍
                sell_ratio = np.random.uniform(*rebalance_params['sell_ratio_range'])
                sell_amount = position['amount'] * sell_ratio
                
                if sell_amount < rebalance_params['min_amount']:
                    logging.warning(f"{currency} 倉位 {i} 賣出量{sell_amount}小於最小交易量{rebalance_params['min_amount']}，跳過該倉位")
                    continue
                    
                logging.info(f"{currency} 倉位 {i} 準備賣出 {sell_ratio*100:.1f}% 持倉，數量: {sell_amount:.4f}")
                
                # 檢查市場狀態
                try: 
                    # 使用最新價格
                    ticker = exchange.fetch_ticker(f"{currency}/USDT")
                    current_price = float(ticker['last'])
                    
                    # 檢查是否有足夠的市場深度
                    orderbook = exchange.fetch_order_book(f"{currency}/USDT")
                    best_bid = orderbook['bids'][0][0] if orderbook['bids'] else 0
                    best_ask = orderbook['asks'][0][0] if orderbook['asks'] else float('inf')
                    
                    spread = (best_ask - best_bid) / best_bid * 100
                    if spread > 1.0:  # 如果買賣差價超過1%
                        logging.warning(f"{currency} 買賣差價過大({spread:.2f}%)，跳過該倉位")
                        continue
                        
                    # 檢查24小時交易量
                    if ticker['quoteVolume'] < 100000:  # 如果24小時交易量小於10萬USDT
                        logging.warning(f"{currency} 24小時交易量過低({ticker['quoteVolume']:.2f} USDT)，跳過該倉位")
                        continue
                        
                    logging.info(f"{currency} 市場檢查通過: 當前價格={current_price:.4f}, "
                               f"買賣差價={spread:.2f}%, 24h交易量={ticker['quoteVolume']:.2f} USDT")
                        
                except Exception as e:
                    logging.error(f"{currency} 檢查市場狀態失敗: {str(e)}")
                    continue
                
                try:
                    # 使用safe_api_call包裝下單操作
                    order = exchange.create_market_sell_order(f"{currency}/USDT", sell_amount)
                    actual_price = float(order['price'])
                    actual_amount = float(order['amount'])
                    
                    position['amount'] -= actual_amount
                    profit_realized = (actual_price - position['entry_price']) * actual_amount
                    position['profit'] -= profit_realized
                    
                    logging.info(f"{currency} 倉位 {i} 賣出成功: 價格={actual_price:.4f}, "
                               f"數量={actual_amount:.4f}, 實現收益={profit_realized:.2f}")
                    
                    # 使用配置的收益分配比例
                    rebalance_amount = profit_realized * rebalance_params['profit_share']
                    for j in range(rebalance_params['min_positions']-1):
                        if positions[j]['profit'] < 0:
                            positions[j]['profit'] += rebalance_amount
                            logging.info(f"{currency} 使用 {rebalance_amount:.2f} USDT補充倉位 {j} 的虧損")
                            break
                    
                    # 更新總收益
                    trade_info[currency]['total_profit'] += profit_realized
                    trade_info[currency]['daily_profit'] += profit_realized
                    trade_info[currency]['monthly_profit'] += profit_realized
                    
                    
                    # 記錄再平衡歷史
                    rebalance_record = {
                        'timestamp': datetime.now().isoformat(),
                        'position_index': i,
                        'sell_amount': actual_amount,
                        'sell_price': actual_price,
                        'profit_realized': profit_realized,
                        'rebalance_amount': rebalance_amount
                    }
                    trade_info[currency]['rebalance_history'].append(rebalance_record)
                    trade_info[currency]['last_rebalance_time'] = datetime.now()
                    trade_info[currency]['rebalance_count'] += 1
                     
                    save_trade_info_to_file(trade_info)  # 儲存到 JSON 文件

                    logging.info(f"{currency} 更新收益: 總收益={trade_info[currency]['total_profit']:.2f}, 日收益={trade_info[currency]['daily_profit']:.2f}")
                    rebalance_success = True
                    
                except ccxt.InsufficientFunds as e:
                    logging.error(f"{currency} 倉位 {i} 餘額不足: {str(e)}")
                    continue
                except ccxt.NetworkError as e:
                    logging.error(f"{currency} 倉位 {i} 網路錯誤: {str(e)}")
                    continue
                except Exception as e:
                    logging.error(f"{currency} 倉位 {i} 賣出失敗: {str(e)}")
                    continue
                    
            except Exception as e:
                logging.error(f"{currency} 倉位 {i} 處理錯誤: {str(e)}")
                continue
                
        if rebalance_success:
            logging.info(f"{currency} 倉位再平衡完成，總計執行{trade_info[currency]['rebalance_count']}次再平衡")
        else:
            logging.info(f"{currency} 本次再平衡未執行任何操作")
            
        return rebalance_success
        
    except Exception as e:
        logging.error(f"{currency} 再平衡過程發生錯誤: {str(e)}")
        return False