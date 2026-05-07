

import json
import pandas

# 打开你的 json 文件（把文件名改成你自己的）



results = {'标题': [], '原价': [], '优惠价': [], '销量': []}

def get_info(file_path):
    global results
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data['result']


    # 商品列表在这一层
    goods_list = data["result"]["data"]["goods_list"]

    result = []
    for goods in goods_list:
        # 标题
        title = goods["title"]

        # 价格信息
        price_info = goods["price_info"]
        price_str = price_info.get("price_str", "")          # 优惠后价格
        market_price_str = price_info.get("market_price_str", "")  # 原价

        # 销量
        sales_tip = goods.get("sales_tip", "")

        # 保存一行
        result.append({
            "标题": title,
            "原价": market_price_str,
            "优惠价": price_str,
            "销量": sales_tip
        })

    # 打印看看

    for item in result:
        results['标题'].append(item['标题'])
        results['原价'].append(item['原价'])
        results['优惠价'].append(item['优惠价'])
        results['销量'].append(item['销量'])

def get():
    global results
    files = [r"D:\tmp\新接口\家居装修1.txt", r"D:\tmp\新接口\家居装修2.txt", r"D:\tmp\新接口\家居装修3.txt", r"D:\tmp\新接口\家居装修4.txt", r"D:\tmp\新接口\家居装修5.txt"]
    for i in files:
        get_info(i)

    df = pandas.DataFrame(results)
    with pandas.ExcelWriter('./爬虫数据.xlsx', engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
        workbook = writer.book
        sheet = workbook.active
        # start_row = sheet.max_row
        df.to_excel(writer, sheet_name='家居装修', startrow=0, index=False, header=True)
if __name__ == '__main__':
    get()