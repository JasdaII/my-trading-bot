import ccxt
import logging
import time
from config import okx_api_key, okx_secret_key, okx_passphrase, SYSTEM_CONFIG
import numpy as np
from functools import lru_cache

def initialize_exchange(max_retries=3, base_delay=2):
    """
    初始化交易所連接，包含重試機制和速率限制
    """
    if not all([okx_api_key, okx_secret_key, okx_passphrase]):
        logging.error("缺少交易所API憑證")
        return None

    for attempt in range(max_retries):
        try:
            delay = base_delay * (2 ** attempt)
            logging.info(f"開始第 {attempt + 1} 次嘗試初始化交易所連接")

            exchange_instance = ccxt.okx({
                'apiKey': okx_api_key,
                'secret': okx_secret_key,
                'password': okx_passphrase,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',  # 只處理現貨市場
                    'adjustForTimeDifference': True,
                    'recvWindow': 60000,
                },
                'rateLimit': 300,  # 降低到300毫秒
                'timeout': 30000,
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            })

            # 使用安全的API調用方式載入市場
            markets = safe_api_call(exchange_instance.load_markets)

            # 過濾掉非現貨市場
            spot_markets = {symbol: market for symbol, market in markets.items() if market['type'] == 'spot'}
            exchange_instance.markets = spot_markets

            # 測試API連接
            status = safe_api_call(exchange_instance.fetch_status)

            if status['status'] == 'ok':
                logging.info("交易所連接成功")
                return exchange_instance
            else:
                logging.warning(f"交易所狀態異常: {status['status']}")

        except ccxt.NetworkError as e:
            if attempt < max_retries - 1:
                logging.warning(f"網路錯誤，{delay}秒後重試: {str(e)}")
                time.sleep(delay)
            else:
                logging.error(f"網路錯誤，達到最大重試次數: {str(e)}")
                return None

        except Exception as e:
            logging.error(f"初始化交易所時發生錯誤: {str(e)}")
            if attempt < max_retries - 1:
                logging.info(f"將在{delay}秒後重試")
                time.sleep(delay)
            else:
                return None

def safe_api_call(func, *args, **kwargs):
    """
    安全的API調用封裝，包含數據驗證
    """
    max_retries = SYSTEM_CONFIG['max_retries']
    retry_delay = SYSTEM_CONFIG['retry_delay']

    for attempt in range(max_retries):
        try:
            time.sleep(1)  # 添加小延遲
            result = func(*args, **kwargs)

            # 如果是 load_markets 或 fetch_status，直接返回結果
            if func.__name__ in ['load_markets', 'fetch_status']:
                return result

            # 如果是 OHLCV 數據，檢查格式
            if isinstance(result, list) and all(isinstance(candle, list) and len(candle) >= 5 for candle in result):
                return result
            else:
                logging.error(f"API調用返回了非預期格式的數據: {result}")
                raise Exception("Malformed data received from API")

        except ccxt.RateLimitExceeded as e:
            if attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)
                logging.warning(f"達到速率限制，{delay}秒後重試: {str(e)}")
                time.sleep(delay)
            else:
                raise
        except ccxt.NetworkError as e:
            if attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)
                logging.warning(f"網路錯誤，{delay}秒後重試: {str(e)}")
                time.sleep(delay)
            else:
                raise
        except Exception as e:
            logging.error(f"API調用錯誤: {str(e)}")
            raise

def get_rsi(symbol, timeframe='4h', periods=14):
    """
    計算指定交易對的 RSI
    """
    try:
        ohlcv = safe_api_call(exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=periods + 20)
        if not ohlcv:
            logging.warning(f"無法獲取 {symbol} 的OHLCV數據")
            return None

        # 確保 OHLCV 數據格式正確
        closes = []
        for candle in ohlcv:
            if isinstance(candle, list) and len(candle) >= 5:  # OHLCV 數據應為長度至少為 5 的列表
                close_price = candle[4]  # 收盤價在第 5 個位置
                if isinstance(close_price, (int, float)):
                    closes.append(float(close_price))
                else:
                    logging.warning(f"無效的收盤價數據: {close_price}")
            else:
                logging.warning(f"無效的 OHLCV 數據格式: {candle}")

        if len(closes) < periods:
            logging.warning(f"不足夠的數據來計算 {symbol} 的 RSI")
            return None

        # 計算 RSI
        deltas = np.diff(closes)
        seed = deltas[:periods]
        up = seed[seed >= 0].sum() / periods
        down = -seed[seed < 0].sum() / periods
        rs = up / down if down != 0 else 100
        rsi = np.zeros_like(closes)
        rsi[:periods] = 100. - 100. / (1. + rs)

        for i in range(periods, len(closes)):
            delta = deltas[i - 1]
            upval = delta if delta > 0 else 0.
            downval = -delta if delta < 0 else 0.
            up = (up * (periods - 1) + upval) / periods
            down = (down * (periods - 1) + downval) / periods
            rs = up / down if down != 0 else 100
            rsi[i] = 100. - 100. / (1. + rs)

        return rsi[-1]
    except ccxt.NetworkError as e:
        logging.error(f"在獲取 {symbol} 的 RSI 時發生網路錯誤: {str(e)}")
        return None
    except ccxt.ExchangeError as e:
        logging.error(f"在獲取 {symbol} 的 RSI 時發生交易所錯誤: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"計算 {symbol} 的 RSI 時發生錯誤: {str(e)}")
        return None

def get_macd(symbol, timeframe='4h', fast_period=12, slow_period=26, signal_period=9):
    """
    計算 MACD 指標
    """
    try:
        ohlcv = safe_api_call(exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=slow_period + 50)
        if not ohlcv:
            logging.warning(f"無法獲取 {symbol} 的OHLCV數據以計算MACD")
            return None

        # 確保 OHLCV 數據格式正確
        closes = []
        for candle in ohlcv:
            if isinstance(candle, list) and len(candle) >= 5:  # OHLCV 數據應為長度至少為 5 的列表
                close_price = candle[4]  # 收盤價在第 5 個位置
                if isinstance(close_price, (int, float)):
                    closes.append(float(close_price))
                else:
                    logging.warning(f"無效的收盤價數據: {close_price}")
            else:
                logging.warning(f"無效的 OHLCV 數據格式: {candle}")

        if len(closes) < slow_period:
            logging.warning(f"不足夠的數據來計算 {symbol} 的 MACD")
            return None

        # 計算 MACD
        ema_fast = np.mean(closes[-fast_period:])
        ema_slow = np.mean(closes[-slow_period:])
        macd_line = ema_fast - ema_slow
        signal_line = np.mean(np.array([macd_line]))
        histogram = macd_line - signal_line
        return {'macd': macd_line, 'signal': signal_line, 'histogram': histogram}
    except ccxt.NetworkError as e:
        logging.error(f"在獲取 {symbol} 的 MACD 時發生網路錯誤: {str(e)}")
        return None
    except ccxt.ExchangeError as e:
        logging.error(f"在獲取 {symbol} 的 MACD 時發生交易所錯誤: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"計算 {symbol} 的 MACD 時發生錯誤: {str(e)}")
        return None


@lru_cache(maxsize=128)  # 使用緩存機制，避免重複計算
def get_bollinger(symbol, timeframe='1h', period=20, deviation=2):
    """
    計算 Bollinger Bands
    :param symbol: 交易對（如 'BTC/USDT'）
    :param timeframe: 時間框架（如 '1h', '4h', '1d'）
    :param period: 計算週期
    :param deviation: 標準差倍數
    :return: 包含上軌、中軌、下軌的字典
    """
    try:
        logging.info(f"開始計算 {symbol} 的 Bollinger Bands，時間框架: {timeframe}，週期: {period}，偏差: {deviation}")
        
        # 獲取 OHLCV 數據
        ohlcv = safe_api_call(exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=period + 20)
        if not ohlcv:
            logging.warning(f"無法獲取 {symbol} 的OHLCV數據以計算 Bollinger Bands")
            return {}
        
        # 提取收盤價數據
        closes = []
        for candle in ohlcv:
            if isinstance(candle, list) and len(candle) >= 5:  # OHLCV 數據應為長度至少為 5 的列表
                close_price = candle[4]  # 收盤價在第 5 個位置
                if isinstance(close_price, (int, float)) and not np.isnan(close_price):  # 排除 NaN 或無效值
                    closes.append(float(close_price))
                else:
                    logging.warning(f"無效的收盤價數據: {close_price}")
            else:
                logging.warning(f"無效的 OHLCV 數據格式: {candle}")
        
        # 檢查數據是否足夠
        if len(closes) < period:
            logging.warning(f"不足夠的數據來計算 {symbol} 的 Bollinger Bands")
            return {}
        
        # 計算 Bollinger Bands
        sma = np.mean(closes[-period:])
        std = np.std(closes[-period:])
        upper_band = sma + deviation * std
        lower_band = sma - deviation * std
        
        logging.info(f"成功計算 {symbol} 的 Bollinger Bands: 上軌={upper_band:.4f}, 中軌={sma:.4f}, 下軌={lower_band:.4f}")
        return {'upper': upper_band, 'middle': sma, 'lower': lower_band}
    
    except ccxt.NetworkError as e:
        logging.error(f"在獲取 {symbol} 的 Bollinger Bands 時發生網路錯誤: {str(e)}")
        return {}
    except ccxt.ExchangeError as e:
        logging.error(f"在獲取 {symbol} 的 Bollinger Bands 時發生交易所錯誤: {str(e)}")
        return {}
    except ValueError as e:
        logging.error(f"在處理 {symbol} 的 OHLCV 數據時發生值錯誤: {str(e)}")
        return {}
    except Exception as e:
        logging.error(f"計算 {symbol} 的 Bollinger Bands 時發生未知錯誤: {str(e)}")
        return {}

def get_volatility(symbol, timeframe='1h', period=20):
    """
    計算年化波動率
    """
    try:
        ohlcv = safe_api_call(exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=period + 20)
        if not ohlcv:
            logging.warning(f"無法獲取 {symbol} 的OHLCV數據以計算波動率")
            return None

        # 確保 OHLCV 數據格式正確
        closes = []
        for candle in ohlcv:
            if isinstance(candle, list) and len(candle) >= 5:  # OHLCV 數據應為長度至少為 5 的列表
                close_price = candle[4]  # 收盤價在第 5 個位置
                if isinstance(close_price, (int, float)):
                    closes.append(float(close_price))
                else:
                    logging.warning(f"無效的收盤價數據: {close_price}")
            else:
                logging.warning(f"無效的 OHLCV 數據格式: {candle}")

        if len(closes) < period:
            logging.warning(f"不足夠的數據來計算 {symbol} 的波動率")
            return None

        # 計算年化波動率
        log_returns = np.diff(np.log(closes))
        annualized_volatility = np.std(log_returns) * np.sqrt(365 * 24)  # 假設每小時採樣
        return annualized_volatility
    except ccxt.NetworkError as e:
        logging.error(f"在獲取 {symbol} 的波動率時發生網路錯誤: {str(e)}")
        return None
    except ccxt.ExchangeError as e:
        logging.error(f"在獲取 {symbol} 的波動率時發生交易所錯誤: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"計算 {symbol} 的波動率時發生錯誤: {str(e)}")
        return None


def calculate_volatility(currency: str, timeframe='1d', period=20) -> float:
    """
    計算指定貨幣的波動率
    :param currency: 貨幣代碼（如 'BTC'）
    :param timeframe: 時間框架（如 '1d' 表示每日數據）
    :param period: 計算波動率的週期（如 20 天）
    :return: 波動率（浮點數）
    """
    try:
        # 獲取 OHLCV 數據
        ohlcv = safe_api_call(exchange.fetch_ohlcv, f"{currency}/USDT", timeframe=timeframe, limit=period + 1)
        if not ohlcv or len(ohlcv) < period:
            logging.warning(f"無法獲取足夠的 {currency} OHLCV 數據以計算波動率")
            return 0.0
        
        # 提取收盤價數據
        closes = [float(candle[4]) for candle in ohlcv if isinstance(candle, list) and len(candle) >= 5]
        if len(closes) < period:
            logging.warning(f"不足夠的 {currency} 收盤價數據以計算波動率")
            return 0.0
        
        # 計算每日收益率（對數收益率）
        log_returns = np.diff(np.log(closes))
        
        # 計算波動率（標準差）
        volatility = np.std(log_returns) * np.sqrt(len(closes))  # 年化波動率
        logging.info(f"{currency} 的波動率: {volatility:.4f}")
        return volatility
    
    except ccxt.NetworkError as e:
        logging.error(f"在獲取 {currency} 的波動率時發生網路錯誤: {str(e)}")
        return 0.0
    except ccxt.ExchangeError as e:
        logging.error(f"在獲取 {currency} 的波動率時發生交易所錯誤: {str(e)}")
        return 0.0
    except Exception as e:
        logging.error(f"計算 {currency} 的波動率時發生未知錯誤: {str(e)}")
        return 0.0




# 初始化交易所實例
try:
    exchange = initialize_exchange()
    if exchange is None:
        logging.error("無法初始化交易所連接")
except Exception as e:
    logging.error(f"初始化交易所時發生錯誤: {str(e)}")
    exchange = None

# 導出實例
__all__ = ['exchange', 'safe_api_call', 'get_rsi', 'get_macd', 'get_bollinger', 'get_volatility']