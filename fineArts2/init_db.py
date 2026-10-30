# -*- coding: utf-8 -*-
"""数据库初始化：建库、建表、创建默认管理员

用法： python init_db.py
数据库连接取自 .env（或 app/config.py 默认值）。
"""
from app import create_app
from app.config import DB_HOST, DB_PORT, DB_NAME, ensure_mysql_database
from app.models import db, Admin


def main():
    print('数据库：mysql://%s:%s/%s' % (DB_HOST, DB_PORT, DB_NAME))

    ensure_mysql_database()
    print('数据库已就绪')

    app = create_app('development')
    with app.app_context():
        db.create_all()
        if Admin.query.first():
            print('管理员已存在，跳过创建')
        else:
            admin = Admin(username=app.config['ADMIN_USERNAME'])
            admin.set_password(app.config['ADMIN_PASSWORD'])
            db.session.add(admin)
            db.session.commit()
            print('默认管理员已创建：%s / %s'
                  % (app.config['ADMIN_USERNAME'], app.config['ADMIN_PASSWORD']))

    print('初始化完成')


if __name__ == '__main__':
    main()
