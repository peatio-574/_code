import requests
from bs4 import BeautifulSoup


cookie = 'PSTM=1745981867; BIDUPSID=8ECA8A9AA5FEA8BF365783A172D08827; H_WISE_SIDS=63145_66230_66393_66529_66586_66592_66602_66654_66680_66694_66687_66616_66771_66786_66791_66800_66805_66852_66855_66599_66881_66918_66938_66935; BD_UPN=12314753; BDORZ=FFFB88E999055A3F8A630C64834BD6D0; H_PS_PSSID=63145_67861_68166_69006_69294_69587_69763_69799_69779_69842_69902_69961_70044_70092_70116_70149_70155_70231_70194_70201_70209_70280_70321_69921_70355_70142_70402_70432_70459_70477_70475_70472_70371_70519_70563_70621; H_PS_645EC=bb39AB8JA1cdcUv0e3VCsAfpuNbcwaRLD4N7K1iqUdsr5JgvIFGvJM%2FhK2tedFAqC%2BnxEihreojG; BAIDUID=87DD05F6B2727829385440B8D25B2ECD:FG=1; BAIDUID_BFESS=87DD05F6B2727829385440B8D25B2ECD:FG=1; WWW_ST=1780063221887'

user_agnet = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36'

headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'cookie': cookie,
    'User-Agent': user_agnet
}

student_id = 24202150102
name = "莫佳仪"
print('='*30)
print('实验三（2）爬取武汉学院信息')
print('='*30)
print(f"学生姓名：{name}",)
print(f"学号: {student_id}")


import requests
from bs4 import BeautifulSoup
#
url = "https://www.baidu.com/s?ie=UTF-8&wd=武汉学院信息"
response = requests.get(url, headers)
response.encoding = response.apparent_encoding
soup = BeautifulSoup(response.text, features='lxml')
info = soup.select('.pc-paragraph_4FVl6')
print(soup)
# info = '武汉学院（Wuhan College），位于湖北省武汉市，是经国家教育部和湖北省人民政府批准成立的民办普通本科高等学校，学校为湖北省大学生创业示范基地，由武汉一丹教科文发展有限公司举办，非营利性公益办学。'
print(info)
