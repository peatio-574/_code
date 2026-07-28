import os
import pandas
from Logger import logger

class ReadData(object):
    @classmethod
    def read_xlsx_row(cls, file, sheetname=0, header=0, index_col=None):
        """按行读取xlsx，[{},{},{}]"""
        try:
            file = os.path.abspath(file)
            pd = pandas.read_excel(file, sheet_name=sheetname, header=header, index_col=index_col, keep_default_na=False).astype(str)  # astype将数据转为str
            col_key = [i for i in pd]
            rows = pd.shape[0]
            datalist = list()
            for row in range(rows):
                # 每行用字典保存
                row_dict = {col: pd[col][row] for col in col_key}
                datalist.append(row_dict)
            # logger.info('%s文件按行读取成功' % file)
            return datalist
        except Exception as e:
            logger.error('%s文件按行读取失败：%s' % (file, e))
            return None

    @classmethod
    def read_xlsx_col(cls, file, sheetname=0, header=0, index_col=None):
        """按列读取xlsx，{col1:[], col2:[], col3:[]}"""
        try:
            file = os.path.abspath(file)
            pd = pandas.read_excel(file, sheet_name=sheetname, header=header, index_col=index_col, keep_default_na=False).astype(str)
            col_key = [i for i in pd]
            rows = pd.shape[0]
            data_dict = dict()
            for col in col_key:
                # 每列用列表保存
                col_list = [pd[col][i] for i in range(rows)]
                data_dict[col] = col_list
            # logger.info('%s文件按列读取成功' % file)
            return data_dict
        except Exception as e:
            logger.error('%s文件按列读取失败：%s' % (file, e))
            return None

if __name__ == '__main__':
    file = '../data/测试数据.xlsx'
    data = ReadData.read_xlsx_row(file)
    # for i in data:
    #     print(i)
    # for k, v in ReadData.read_xlsx_col(file).items():
    #     print(k, v)