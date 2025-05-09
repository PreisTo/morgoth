import sqlite3
from morgoth.configuration import morgoth_config


def create_database_table():
    create_table = """CREATE TABLE IF NOT EXISTS grb_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grb TEXT NOT NULL,
        type TEXT NOT NULL,
        det TEXT NOT NULL,
        version INTEGER,
        url TEXT NOT NULL
    )"""
    with sqlite3.connect(morgoth_config["file_version_database"]) as conn:
        cursor = conn.cursor()
        cursor.execute(create_table)
        conn.commit()


def add_entry(grb, dtype, det, version, url):
    insertion = """INSERT INTO grb_data(grb,type,det,version,url)
    VALUES(?,?,?,?,?)"""
    with sqlite3.connect(morgoth_config["file_version_database"]) as conn:
        cursor = conn.cursor()
        cursor.execute(insertion, (grb, dtype, det, version, url))
        conn.commit()


def get_url(grb, dtype, det, version):
    select = """SELECT * FROM grb_data WHERE grb=? AND type=? AND det=? AND version=?"""
    with sqlite3.connect(morgoth_config["file_version_database"]) as conn:
        cursor = conn.cursor()
        cursor.execute(select, (grb, dtype, det, version))
        row = cursor.fetchone()
    if row is not None:
        url = row[5]
    else:
        url = None
    return url
