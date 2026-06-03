import pandas as pd
from pandas import DataFrame
import backtrader as bt
import settings
from logger import create_log

logger = create_log('manager_common')


class StockData:
    def __init__(self, kline_file_path: str):
        self.kline_file_path = str(kline_file_path)
        self.kline_file_relative_path = str(kline_file_path).replace(str(settings.stock_data_root) + '/', '')
        self.stock_code = ''
        self.stock_name = ''
        self.data_source = ''
        if '_' in self.kline_file_relative_path:
            parts = self.kline_file_relative_path.split('/')
            if len(parts) >= 2:
                file_name = parts[-1].replace('.csv', '')
                self.stock_code, self.stock_name = file_name.split('_', 1) if '_' in file_name else (file_name, '')
                self.data_source = parts[0] if len(parts) >= 2 else ''

        try:
            self.data = self.get_data_from_csv(kline_file_path)
        except Exception as e:
            logger.warning(f"历史K线数据加载失败：{str(e)}")
            return

        self.data_length = len(self.data.p.dataname)
        logger.info(f"【数据检查】有效数据量：{self.data_length} 天")

        market_series = self.data.p.dataname.get('market', pd.Series(['HK']))
        self.market = market_series.iloc[0] if not market_series.empty else None

        self.start_date = self.data.p.dataname.index[0].strftime('%Y-%m-%d')
        self.end_date = self.data.p.dataname.index[-1].strftime('%Y-%m-%d')


    def get_stock_data(self):
        return {
            'kline_file_path': self.kline_file_path,
            'kline_file_relative_path': self.kline_file_relative_path,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'data_source': self.data_source,
            'market': self.market,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'data_length': self.data_length
        }

    def get_data_from_csv(self,kline_file_path):
        """
        从CSV文件加载K线数据，返回backtrader可用的数据对象

        参数:
            csv_path: CSV文件路径

        返回:
            CustomPandasData: backtrader数据对象
        """
        df = pd.read_csv(
            kline_file_path,
            parse_dates=['date'],
            index_col='date'
        )

        class CustomPandasData(bt.feeds.PandasData):
            params = (
                ('datetime', None),
                ('open', 'open'), ('high', 'high'), ('low', 'low'), ('close', 'close'), ('volume', 'volume'),
                ('market', 'market'),
                ('openinterest', -1)
            )

        data_feed = CustomPandasData(dataname=df)
        data_feed.timeframe = bt.TimeFrame.Days
        data_feed.compression = 1
        return data_feed

def standardize_stock_data(df: DataFrame, stock_code: str, stock_name: str, market) -> DataFrame:
    """
    标准化股票数据为统一的英文表头格式
    """
    # 添加股票基本信息
    df['stock_code'] = stock_code
    df['stock_name'] = stock_name
    df['market'] = market

    # 定义中文到英文的列名映射
    cn_to_en_map = {
        '日期': 'date',
        '交易日期': 'date',
        '开盘': 'open',
        '开盘价': 'open',
        '收盘': 'close',
        '收盘价': 'close',
        '最高': 'high',
        '最高价': 'high',
        '最低': 'low',
        '最低价': 'low',
        '成交量': 'volume',
        '成交量(股)': 'volume',
        '成交额': 'amount',
        '成交额(元)': 'amount',
        '成交额(港元)': 'amount',
        '振幅': 'amplitude',
        '振幅(%)': 'amplitude',
        '涨跌幅': 'change_pct',
        '涨跌幅(%)': 'change_pct',
        '涨跌额': 'change',
        '换手率': 'turnover_rate',
        '换手率(%)': 'turnover_rate'
    }

    # 重命名列
    renamed_columns = {col: cn_to_en_map.get(col, col) for col in df.columns}
    df = df.rename(columns=renamed_columns)

    # 确保所有必需的列存在
    required_columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount',
                        'stock_code', 'stock_name', 'market']

    # 添加缺失的列并设置为NaN
    for col in required_columns:
        if col not in df.columns:
            df[col] = pd.NA

    # 确保日期格式正确
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])

    # 只保留需要的列并按日期排序
    df = df[required_columns].sort_values('date')

    return df