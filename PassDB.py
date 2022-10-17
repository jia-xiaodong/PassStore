#!/usr/bin/python
# -*- coding: utf-8 -*-

import sqlite3
from enum import Enum


class KeychainColumn(Enum):
    """
    Keychain数据表的各列组成
    """
    id = 0
    loc = 1
    usr = 2
    pwd = 3
    COUNT = 4


class KeychainRecord:
    """
    Keychain数据表的一条记录
    """
    def __init__(self, location: str, username: str = None, password: str = None, sn: int = 0):
        self._sn = sn
        self._loc = location
        self._usr = username
        self._pwd = password
        self._dirty_flags = set()

    @property
    def sn(self):
        return self._sn

    @sn.setter
    def sn(self, value):
        self._sn = value

    @property
    def loc(self):
        return self._loc

    @loc.setter
    def loc(self, value):
        if self._loc == value:
            return
        self._loc = value
        self._dirty_flags.add(KeychainColumn.loc)

    @property
    def usr(self):
        return self._usr

    @usr.setter
    def usr(self, value):
        if self._usr == value:
            return
        self._usr = value
        self._dirty_flags.add(KeychainColumn.usr)

    @property
    def pwd(self):
        return self._pwd

    @pwd.setter
    def pwd(self, value):
        if self._pwd == value:
            return
        self._pwd = value
        self._dirty_flags.add(KeychainColumn.pwd)

    @property
    def unsaved_fields(self):
        return self._dirty_flags

    def after_saving(self):
        self._dirty_flags.clear()


class PassDatabase:
    """
    密码数据库
    """
    def __init__(self, filename: str):
        self._filename = filename
        self._con = sqlite3.connect(filename)

    def close(self):
        self._con.close()
        self._filename = None

    def select_all(self):
        records = []
        try:
            sql = 'SELECT id,loc,usr,pwd FROM keychain'
            cur = self._con.cursor()
            cur.execute(sql)
            for s, l, u, p in cur.fetchall():
                records.append(KeychainRecord(l, u, p, s))
        except Exception as e:
            print(f'Error on reading: {e}')
        finally:
            return records

    def insert(self, record: KeychainRecord):
        try:
            sql = 'INSERT INTO keychain (loc, usr, pwd) VALUES(?,?,?)'
            args = (record.loc, record.usr, record.pwd)
            cur = self._con.cursor()
            cur.execute(sql, args)
            self._con.commit()
            record.sn = cur.lastrowid
            record.after_saving()
        except Exception as e:
            print(f'Error on insertion: {e}')

    def update(self, record: KeychainRecord):
        args = {}
        cols = []
        for i in record.unsaved_fields:
            if i == KeychainColumn.loc:
                args['loc'] = record.loc
                cols.append('loc=:loc')
            elif i == KeychainColumn.usr:
                args['usr'] = record.usr
                cols.append('usr=:usr')
            elif i == KeychainColumn.pwd:
                args['pwd'] = record.pwd
                cols.append('pwd=:pwd')
        try:
            if len(cols) > 0:
                sql = 'UPDATE keychain SET %s WHERE id=%d' % (', '.join(cols), record.sn)
                self._con.execute(sql, args)
                self._con.commit()
                record.after_saving()
        except Exception as e:
            print(f'Error on update: {e}')

    def delete(self, sn):
        try:
            self._con.execute('DELETE FROM keychain WHERE id=?', (sn,))
            self._con.commit()
        except Exception as e:
            print(f'Error on deletion: {e}')

    @staticmethod
    def create_db(filename: str):
        try:
            sql = '''CREATE TABLE keychain (
                            id  INTEGER PRIMARY KEY UNIQUE NOT NULL,
                            loc TEXT NOT NULL,
                            usr TEXT NOT NULL,
                            pwd TEXT)'''
            con = sqlite3.connect(filename)
            con.executescript(sql)
            con.commit()
            #
            return PassDatabase(filename)
        except Exception as e:
            print(f'Error on creation of DB: {e}')
            return None

    @staticmethod
    def validate(filename: str):
        """
        校验一个文件是否符合本数据库的结构
        :param filename:
        :return:
        """
        def is_column_identical(cursor, table_name: str, table_columns):
            cursor.execute(f'PRAGMA table_info ({table_name})')
            structs = cursor.fetchall()
            result = (structs[i][1] == table_columns[i] for i in range(len(table_columns)))
            return all(result)
        is_valid = False
        try:
            with sqlite3.connect(filename) as con:
                cur = con.cursor()
                tables = {'keychain': [KeychainColumn(i).name for i in range(KeychainColumn.COUNT.value)]}
                is_valid = all(is_column_identical(cur, i, j) for i, j in tables.items())
        except Exception as e:
            print(f'Error on validation of DB: {e}')
        finally:
            return is_valid

    @property
    def source(self):
        return self._filename

