import os
import re


def clean_filename(filename):
    """清理文件名，只保留允许的字符"""
    # 分离文件名和扩展名
    name, ext = os.path.splitext(filename)

    # 定义允许的字符模式
    pattern = r'[^\u4e00-\u9fa5a-zA-Z0-9_\-=\+\.,，。&|~！! ]'

    # 替换不符合的字符为空字符串
    clean_name = re.sub(pattern, '', name)

    # 去除首尾空格，将多个连续空格替换为单个空格
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()

    # 如果清理后文件名为空，使用原文件名的哈希值
    if not clean_name:
        clean_name = 'image'

    return clean_name + ext


def batch_rename_images(directory):
    """批量重命名目录下的所有图片文件"""
    if not os.path.exists(directory):
        print(f"目录不存在: {directory}")
        return

    # 支持的图片扩展名
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

    # 获取所有图片文件
    files = [f for f in os.listdir(directory)
             if os.path.isfile(os.path.join(directory, f))
             and os.path.splitext(f)[1].lower() in image_extensions]

    if not files:
        print("目录下没有找到图片文件")
        return

    print(f"找到 {len(files)} 个图片文件")
    print("=" * 80)

    renamed_count = 0
    for old_name in files:
        new_name = clean_filename(old_name)

        # 如果文件名没有变化，跳过
        if old_name == new_name:
            print(f"跳过 (无需修改): {old_name}")
            continue

        old_path = os.path.join(directory, old_name)
        new_path = os.path.join(directory, new_name)

        # 如果新文件名已存在，添加序号避免冲突
        if os.path.exists(new_path):
            name, ext = os.path.splitext(new_name)
            counter = 1
            while os.path.exists(new_path):
                new_name = f"{name}_{counter}{ext}"
                new_path = os.path.join(directory, new_name)
                counter += 1

        try:
            os.rename(old_path, new_path)
            print(f"✓ 重命名成功:")
            print(f"  旧: {old_name}")
            print(f"  新: {new_name}")
            renamed_count += 1
        except Exception as e:
            print(f"✗ 重命名失败: {old_name}")
            print(f"  错误: {e}")

    print("=" * 80)
    print(f"完成！共重命名 {renamed_count} 个文件")


if __name__ == '__main__':
    # 目标目录
    target_dir = r"D:\_code\spider_xhs\数据\小红书号：2287611602_Heeeeeee_2026-06-03\images"

    print(f"开始处理目录: {target_dir}")
    batch_rename_images(target_dir)
