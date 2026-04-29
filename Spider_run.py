


import requests
def demo():
    import xml.etree.ElementTree as ET
    from datetime import datetime

    # 你的文件路径（改成你本地路径）
    KML_FILE = r"C:\Users\Administrator\Downloads\腾冲市～黑鱼河2026-02-06.txt"

    # 命名空间
    ns = {
        "kml": "http://www.opengis.net/kml/2.2",
        "gx": "http://www.google.com/kml/ext/2.2"
    }

    # 加载并解析 XML
    tree = ET.parse(KML_FILE)
    root = tree.getroot()

    # ====================== 1. 提取基本信息 ======================
    doc = root.find("kml:Document", ns)
    track_name = doc.find("kml:name", ns).text
    print("轨迹名称:", track_name)

    # 提取 ExtendedData 里的关键数据
    ext_data = doc.find("kml:ExtendedData", ns)
    data_items = {}
    for data in ext_data.findall("kml:Data", ns):
        name = data.get("name")
        value = data.find("kml:value", ns).text
        data_items[name] = value

    # 打印核心统计
    print("总里程: {:.2f} 米".format(float(data_items.get("Distance", 0))))
    print("累计爬升: {:.2f} 米".format(float(data_items.get("ElevationGain", 0))))
    print("累计下降: {:.2f} 米".format(float(data_items.get("ElevationLoss", 0))))
    print("起点:", data_items.get("PosStartName"))
    print("终点:", data_items.get("PosEndName"))

    # ====================== 2. 提取轨迹点 ======================
    track = doc.find(".//gx:Track", ns)
    coords = track.findall("gx:coord", ns)
    times = track.findall("kml:when", ns)

    print(f"\n轨迹点数: {len(coords)}")

    # 解析每个点
    points = []
    for coord, time in zip(coords, times):
        # 经纬度、海拔
        lon, lat, alt = coord.text.strip().split()
        # 时间
        time_str = time.text.strip()
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except:
            dt = time_str

        points.append({
            "经度": float(lon),
            "纬度": float(lat),
            "海拔": float(alt),
            "时间": dt
        })

    # 打印前5个点示例
    print("\n前5个轨迹点：")
    for i, p in enumerate(points[:5]):
        print(f"{i + 1}. 纬度:{p['纬度']:.6f} 经度:{p['经度']:.6f} 海拔:{p['海拔']:.1f} 时间:{p['时间']}")

    # ====================== 3. 提取起点/终点（稳定不报错） ======================
    print("\n=== 起点/终点 ===")
    for mark in doc.findall(".//kml:Placemark", ns):
        name = mark.find("kml:name", ns)
        point = mark.find("kml:Point/kml:coordinates", ns)

        # 修复1：判断元素是否存在
        if name is not None and point is not None and name.text in ["起点", "终点"]:
            coord_text = point.text.strip()

            # 修复2：自动处理 2个值 或 3个值 的坐标（有无海拔都兼容）
            parts = coord_text.split()
            if len(parts) == 3:
                lon_p, lat_p, alt_p = parts
            elif len(parts) == 2:
                lon_p, lat_p = parts
                alt_p = "无海拔"
            else:
                continue  # 格式异常直接跳过

            # 输出结果
            print(f"{name.text}: 纬度{lat_p} 经度{lon_p} 海拔{alt_p}")


def api():
    url = 'https://www.2bulu.com/space/downtrackByWeb.htm?trackIdDes=eY5g%2BVGYc%2BjPGQ0UPEUA%2FyS3s6ki0WoI&type=1'

    headers = {
        # 'Content-Length': '5000',
        'Cache-Control': 'max-age=0',
        'host': 'www.2bulu.com',
        'sec-ch-ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        'Upgrade-Insecure-Requests': '1',
        'sec-ch-ua-platform': "Windows",
        'origin': 'https://www.2bulu.com',
        'referer': 'https://www.2bulu.com/track/t-Lk8EnMd4uKvp%252FR2KBg5Tzw%253D%253D.htm',
        'content-type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'cookie': 'Hm_lvt_bed4e06c9c336e6fec0b7611aeefdc73=1777444974; HMACCOUNT=F0B428A55970AE0E; SESSION=Y2M3OTMzZmQtMDcwZC00YzI1LWE1NGUtZTBmZGQ4ZDVkZjMy; Hm_lpvt_bed4e06c9c336e6fec0b7611aeefdc73=1777444986; _c_WBKFRo=PUPVNPmB9XSlaADhmWNjsHrDaJm3Kra1hkix0BRC; _nb_ioWEgULi=; token=YMpknC9%2BMwN6aO9jMiADdw%3D%3D; utoken=eM4FXXgJRFLIsHF%2FSk8TiQ%3D%3D_captchaVerifyParam=%257B%2522sceneId%2522%253A%2522g6a4jdjn%2522%252C%2522certifyId%2522%253A%2522aKcVxrAcb1%2522%252C%2522deviceToken%2522%253A%2522V0VCI2FiMDM0ZWMwNjQzZjkxMzk5ZWIzM2UwNjJkYzdmYWUxLWgtMTc3NzQ0NTcyMTI1Ny0yYTU5ZGQ3OTBjOGQ0YzEyOGM1YzIzNjY0YjA0OTc0NyNSZ1pNNTRyQVQ4dGdIbzRlOWdkN3VER1R6UUY4b2ZSa0ZFUVNUMmhpSDN0amRNNDlQWE02NVl5ZHpCTjVHM0pSYjhwakljRVRFUVc0K2dNY21ERTE4aW1jSGdWTnM4T2QyOGUvWERlRG1oaktuc0VKWFR3akJ1WW9iUXJTazYxV1RnbFJwSnB6N29KZHJHSGJoa3RvejZDbGRaTXNOUVUzT1NXc3YydkR1U0JxTW1JR1l5alIvMmVjbGFuYWVBc3B4WUJtY0VKbWVhV0I3RlcwVzdudVZsNFJkTGVqMm9HbHhaMFFOVzJuOG1HTlNKNDE1QXM0eCs1cEk3SkxKdXhZSzZOc2x4emV4NjFTMG1OMzB3SmxhNGQ0Y0pleVpvYi90V1VxYTRCVS84SW8vdFVsMmU1NWhVemtmVnQ5YTh0RER6djU0S3Q0d2FZanRhWW1UNmIzRW1NSENaQlBETWlPVitmYS9tWUtHNHZoUzVHK1kwZE5tUUpaNTFmR2FVUTdUVEkyOVdYR3NSR2NzcWpTTVB0clRBNkpWT05FakEzZ3BEMTJHRFZLSDVDbHFGNjREV2tUU1dIYisyZE1tREtra3Biek9YdUxnd2VWUUFxYVhYNGdRNWsvb1RPWUljL0g1VnJ2QU52TzRaMVlVMDhqajdDOFRxdlpGRUZaRkY5ajN3bVdDR1Rrb01FbTF2clc3VW1HT1VUTVpwaFZGcUtqMFVIWGo0SnZQRXFBYW5LUDM4UG8wc3VzLzd3T3Q4bUtlazE5Mm5MMUQ4UkM0VTg4eUVaVkIzekFjdEZuQXhPQmlPb2dGSytDKzF2cVJpVHNXWmtCeHFmSzF2WmdGTm5uV1pxTm54Q0crZWk5OFlQRnFkSUtiVzhleVdYQXQ2elFYVkpTbWNIUUNJbVBoUUdyZERyVTd5YU01SXUvUmk0VkxGWkE0RE1BQzVHcDN1SWtpak5MNU85SVlYeWMzWlRySFhNMmNKMXpBVndEMmhBYWpGMTd0Vy9YakRjMFNYbWZHNmhhV2xoTU1KbnFFSWZGaE56TGlMMFB4VVJTZlVNbm9SRzgxMk9yMlNrQjVNUW1oTGp2TndCUkxBbDNDMldDIzE4NiNjNTMzYTJiOTlkYTIyZmI2NGI0NjgzMTU4MTJjNzliMQ%253D%253D%2522%252C%2522data%2522%253A%2522JRMnXw5SXyMhXCALRQRHM3j5c2cHGhRkTB0TY2t4IeJQjj2N4KV0QAIYF6lJ1udK5a9mcixTDxi2qsLpWOwuOX8zAnk1P1EKCjEHXn1RdqhUciRHPAZELhE1F0Ija2XdSAeTJRpkDeBKP54IhFYRj1iaaJRtni5SL0eYAq8RR7V4fD9mJnFbRWNTAXx%252FSWQAwF0DGN9SeVYFEil3wTxWAz8bVPxemjB405NkXR8ubCUYrGphSDueDTeNnj1iZ2IrOzR5FmIUPFxVJSgoNG0uW2wPYeMEShDsphRMRS5GqysmQr9MwzgkuQGCOGNbBgORQg9vlktXA2ZhOBJbBWutiijMaTS4Bn4liAIBEGN9YQoPUgg5Q7ZxDkdjXz97HwdWL6U28VAkt%252BgiEw6U3ukwVCEqOeE7LbPXqHIbxoW7W4BNdHoHPiloEWlvSD8tAHQJIFBXBhgDZMVVvUlgD9R8aZZQhXBozTtXKutlIiZyOJI%252FP8NjEC9dARDp3MuCwImbEyU9FMoXbQMVNxoFZv4zQygXITRMYHhkT88AawobllkckhvBXUYNogo6txsichlnVZowLqlC4n%252BnVLmmeFMAtF9xZAxAcCpQLRoxHKxUZylYcjpYRIYRFh0zTHMbbGpzHB434gY%252Ba3FPtahzH5wQU4MPJXY6OA0HVJoLU%252BpMS%252BZZfRM7EElEYSXXdEdhQQfLfCEhNDwgJ3wIMFSDHAM1VfPjcnsmmCYMZhlDYnYL9xQMAmb2Zg4yecz%252B6LqvJ%252BgJP4R3bUQ6LzwlK09Bak9ZYCAbPiPqfSEfMkiXXV8VUgnWQSy0L0A7FDbaemYXcaIy1xVvf0UgUXGEWl6yFYpwzTGXkS8QJ1gTBnNhlz8ZMiVcUGB8AjkeKHvKLC54SMciLjgLMJ99QyEUVzPQ%252BaVWeSU63CAXbhmeP0tV8GTo0ZVOCzBkC1hVZXwwQi5LTEEwFw12fglyNAgHVKFMLXQFTXOLGB98uA1IQZzaLkl9VbCMQGLB6I51HyQW2IYSO0rKXnB0Vz4OSEEMfl0fEywQ3jpddei2fk5pYi06JSmLW2kWMAc5N3VLwTd4gjykWXE4PmWt4i%252FmDwuglQYIawHkERt4WAYtfXlvs39GgnNMM3ZWOhA6IAx2KSUnPm5V6mUxYVe%252FRlKCCxWtc6E9VHZANqO1eCKpapUzI0RZUkbBdwssbE1%252BFiZZCsViv1cQF0lhNUctJSp7KCYIUgsxNRRYAxROqCEmTTNWkBAzECsWoXdWTU9sBJfA57NQih2kAjTiSVcDLQhiInlqSFZicrsPXCUZXWgvIRpuPBV4O3wwGZKgEmSjRSVeHlApKaoWeC1eFf%252FaKDISwVVVjzVyTH5rryikYChqATJhFGDWEStcYx0jmiETQAFNOHFvVRVTTWIhfCprDRrgiUYNAbIP0kBLNx6EXFXQHgl6obo7U5VRz0jbO%252BQuRUBwNURFGNiLtk1cJBVYaPEkV0AeUz0SEg1tnhYLfBMjV18zKmYKVBSv56VMUES3RWs5rF0yv5lW1dQp6LJ0WZdcEsdZUkYfTlAuGm1pPXE9fXsEi0jjWm8Kq0EdcZI6E8UJW1LHAqmaHjYhI10MtDT4biZOT0NkHyIVzyNdcl5Kpw9tMSITZ1UrFmMMUI1iak8OeSNmTWE%252F19VZC0B7ihoQz1BuE0KV0UC5XYoWbl100TTLMk%252B7agZrbVoNRBJVatjacmaVX0U%252FWmsbNvIJOBXsKrwslgchOx0OdrEdCxqFGbECY3XPMhrtHI%252B9jGc8MKktPSXzvPc%252FlJahVSMQRV0JUiN5djbRvzQXW0V%252BeBNbYkwNbQmONHApDwFqHkV6ThQgI3Bf5zpiESjxKTMEjQaXgxd4akQoPeJq62tVF1AyZ2RoPXYjcHFJa2pV8YUoTAcbXhEbG3Q4TGFQHR9t9dJOm2c3Q0kWIuY8P0ooiEpt8WZlC2znkpqS3TRUfjN8VgdLTFtuayogGsRwkmHMqlyOZcF%252BY3LltmteSutAz3R4WAF%252Foi8cl8mxb1gHaHRFM0nxQ3j4CRR67W8iI3BiOxoDBGhFC%252FhEIjL6nFtcTkBgJ2BhdR7fZxIGAHBif2pZZ88yKVrZQGlhCVdlAoa1miBnRXgGUIX6Fzk%252BySRfZ1NBcj5CBEu%252FBHRnBQltbWYmQnRbQtBkaUgcnX5rNno7VkAkZSIRAGYRYofp2C6kOwCpVRIDb6XL6yL0%252FTMnMhtwOtAZIT8eISdqWH8Ge275VHV4RBLceG0SUXNqbAtAfEoDd0VsCKhtEU9TQ2oYCjH2XzMuQW2IUQAfatVqQZ5%252BbZscTHJpWFZ%252FOARsUB0YQk4g3A5rdk8%252BCSMJdESwDyIBWy8C0w%253D%253D%2522%257D&_sceneId=g6a4jdjn'
    }
    response = requests.post(url, headers=headers).content.decode('utf-8')
    print(response)


# ... existing code ...

def download_track():
    """
    下载轨迹文件的 POST 请求
    """
    url = "https://www.2bulu.com/space/downtrackByWeb.htm"

    # 查询参数
    params = {
        "trackIdDes": "eY5g+VGYc+jPGQ0UPEUA/yS3s6ki0WoI",
        "type": "1"
    }

    # 请求头
    headers = {
        "Host": "www.2bulu.com",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Origin": "https://www.2bulu.com",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Referer": "https://www.2bulu.com/track/t-Lk8EnMd4uKvp%2FR2KBg5Tzw%3D%3D.htm",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": "Hm_lvt_bed4e06c9c336e6fec0b7611aeefdc73=1777444974; HMACCOUNT=F0B428A55970AE0E; SESSION=Y2M3OTMzZmQtMDcwZC00YzI1LWE1NGUtZTBmZGQ4ZDVkZjMy; Hm_lpvt_bed4e06c9c336e6fec0b7611aeefdc73=1777444986; _c_WBKFRo=PUPVNPmB9XSlaADhmWNjsHrDaJm3Kra1hkix0BRC; _nb_ioWEgULi=; token=YMpknC9%2BMwN6aO9jMiADdw%3D%3D; utoken=eM4FXXgJRFLIsHF%2FSk8TiQ%3D%3D"
    }

    # 表单数据（已解码）
    captcha_verify_param = '{"sceneId":"g6a4jdjn","certifyId":"aKcVxrAcb1","deviceToken":"V0VCI2FiMDM0ZWMwNjQzZjkxMzk5ZWIzM2UwNjJkYzdmYWUxLWgtMTc3NzQ0NTcyMTI1Ny0yYTU5ZGQ3OTBjOGQ0YzEyOGM1YzIzNjY0YjA0OTc0NyNSZ1pNNTRyQVQ4dGdIbzRlOWdkN3VER1R6UUY4b2ZSa0ZFUVNUMmhpSDN0amRNNDlQWE02NVl5ZHpCTjVHM0pSYjhwakljRVRFUVc0K2dNY21ERTE4aW1jSGdWTnM4T2QyOGUvWERlRG1oaktuc0VKWFR3akJ1WW9iUXJTazYxV1RnbFJwSnB6N29KZHJHSGJoa3RvejZDbGRaTXNOUVUzT1NXc3YydkR1U0JxTW1JR1l5alIvMmVjbGFuYWVBc3B4WUJtY0VKbWVhV0I3RlcwVzdudVZsNFJkTGVqMm9HbHhaMFFOVzJuOG1HTlNKNDE1QXM0eCs1cEk3SkxKdXhZSzZOc2x4emV4NjFTMG1OMzB3SmxhNGQ0Y0pleVpvYi90V1VxYTRCVS84SW8vdFVsMmU1NWhVemtmVnQ5YTh0RER6djU0S3Q0d2FZanRhWW1UNmIzRW1NSENaQlBETWlPVitmYS9tWUtHNHZoUzVHK1kwZE5tUUpaNTFmR2FVUTdUVEkyOVdYR3NSR2NzcWpTTVB0clRBNkpWT05FakEzZ3BEMTJHRFZLSDVDbHFGNjREV2tUU1dIYisyZE1tREtra3Biek9YdUxnd2VWUUFxYVhYNGdRNWsvb1RPWUljL0g1VnJ2QU52TzRaMVlVMDhqajdDOFRxdlpGRUZaRkY5ajN3bVdDR1Rrb01FbTF2clc3VW1HT1VUTVpwaFZGcUtqMFVIWGo0SnZQRXFBYW5LUDM4UG8wc3VzLzd3T3Q4bUtlazE5Mm5MMUQ4UkM0VTg4eUVaVkIzekFjdEZuQXhPQmlPb2dGSytDKzF2cVJpVHNXWmtCeHFmSzF2WmdGTm5uV1pxTm54Q0crZWk5OFlQRnFkSUtiVzhleVdYQXQ2elFYVkpTbWNIUUNJbVBoUUdyZERyVTd5YU01SXUvUmk0VkxGWkE0RE1BQzVHcDN1SWtpak5MNU85SVlYeWMzWlRySFhNMmNKMXpBVndEMmhBYWpGMTd0Vy9YakRjMFNYbWZHNmhhV2xoTU1KbnFFSWZGaE56TGlMMFB4VVJTZlVNbm9SRzgxMk9yMlNrQjVNUW1oTGp2TndCUkxBbDNDMldDIzE4NiNjNTMzYTJiOTlkYTIyZmI2NGI0NjgzMTU4MTJjNzliMQ==","data":"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"}'

    data = {
        "_captchaVerifyParam": captcha_verify_param,
        "_sceneId": "g6a4jdjn"
    }

    try:
        # 发送 POST 请求 - 使用 Session 保持连接
        session = requests.Session()
        response = session.post(url, params=params, headers=headers, data=data)

        # 打印调试信息
        print(f"请求URL: {response.url}")
        print(f"请求方法: POST")
        print(f"状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        print(f"响应内容长度: {len(response.content)} bytes")

        # 检查响应状态
        if response.status_code == 200:
            print("请求成功！")
            # 如果需要保存文件
            with open('track_file.kml', 'wb') as f:
                f.write(response.content)
            print("文件已保存为 track_file.kml")
        else:
            print(f"请求失败，状态码: {response.status_code}")
            print(f"响应内容: {response.text[:500]}")

        return response

    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None


if __name__ == "__main__":
    download_track()
