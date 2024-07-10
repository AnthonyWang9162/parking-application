import streamlit as st
import sqlite3
import random
from datetime import datetime
import pandas as pd
import io
import time
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# 获取字体文件路径
FONT_PATH = 'NotoSansTC-SemiBold.ttf'  # 确保将字体文件上传到 Streamlit Cloud 的文件夹

# 设置 Google Drive API 凭据
creds = Credentials.from_service_account_info(st.secrets["google_drive"])
service = build('drive', 'v3', credentials=creds)

def download_db(file_id, destination):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(destination, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

def upload_db(source, file_id):
    file_metadata = {'name': '抽籤管理系統.db'}
    media = MediaFileUpload(source, mimetype='application/x-sqlite3')
    updated_file = service.files().update(
        fileId=file_id,
        media_body=media
    ).execute()

def get_db_connection():
    # 使用本地 SQLite 数据库文件
    db_file_path = '/tmp/抽籤管理系統.db'
    # 确保下载数据库文件到临时路径
    download_db('1_TArAUZyzzZuLX3y320VpytfBlaoUGBB', db_file_path)  # 替换为你的数据库文件 ID
    conn = sqlite3.connect(db_file_path)
    return conn

def perform_lottery(current):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT 車位編號 FROM 停車位 WHERE 使用狀態 = '抽籤'")
    spaces = [space[0] for space in cursor.fetchall()]

    cursor.execute("SELECT 單位, 姓名, 姓名代號 FROM 申請紀錄 WHERE 期別 = ? AND 身分註記 = '一般'", (current,))
    participants = cursor.fetchall()

    random.shuffle(participants)

    results, waitlist = [], []

    for i in range(len(participants)):
        if i < len(spaces):
            results.append((spaces[i], participants[i]))
        else:
            waitlist.append(participants[i])

    conn.close()

    results_df = pd.DataFrame([(unit, mask_name(name), space) for space, (unit, name, employee_id) in results],
                              columns=['單位', '姓名', '車位號碼'])
    waitlist_df = pd.DataFrame([(unit, mask_name(name), f"備取{i+1}") for i, (unit, name, employee_id) in enumerate(waitlist)],
                               columns=['單位', '姓名', '車位號碼'])

    combined_df = pd.concat([results_df, waitlist_df], ignore_index=True)
    return results, waitlist, results_df, waitlist_df, combined_df

def insert_lottery_results(current, results, waitlist):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for space, (unit, name, employee_id) in results:
            cursor.execute("INSERT INTO 抽籤繳費 (期別, 姓名代號, 車位編號, 繳費狀態) VALUES (?, ?, ?, '未繳費')",
                        (current, employee_id, space))

        for i, (unit, name, employee_id) in enumerate(waitlist):
            backup_space_id = f"備取{i+1}"
            cursor.execute("INSERT INTO 抽籤繳費 (期別, 姓名代號, 車位編號, 繳費狀態) VALUES (?, ?, ?, '未繳費')",
                        (current, employee_id, backup_space_id))
    finally:
        conn.commit()
        db_file_path = '/tmp/抽籤管理系統.db'
        upload_db(db_file_path, '1_TArAUZyzzZuLX3y320VpytfBlaoUGBB')  # 替换为你的数据库文件 ID
        conn.close()

def generate_title(year, quarter):
    if quarter == 1:
        text = f"總管理處{year}年第1期地下停車場員工自用車停車位抽籤結果"
    elif quarter == 2:
        text = f"總管理處{year}年第2期地下停車場員工自用車停車位抽籤結果"
    elif quarter == 3:
        text = f"總管理處{year}年第3期地下停車場員工自用車停車位抽籤結果"
    elif quarter == 4:
        text = f"總管理處{year}年第4期地下停車場員工自用車停車位抽籤結果"
    return text
def convert_df_to_pdf(df):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    year, quarter = get_quarter(today.year, today.month)
    Taiwan_year = year - 1911
    date = f"{Taiwan_year:03d}年{today.month:02d}月{today.day:02d}日"
    title_text = generate_title(Taiwan_year, quarter)

    # 注册字体
    pdfmetrics.registerFont(TTFont('NotoSans', FONT_PATH))

    # 自定义样式
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CustomTitle', fontName='NotoSans', fontSize=16, spaceAfter=20, alignment=1, textColor=colors.black))
    styles.add(ParagraphStyle(name='CustomTableHeader', fontName='NotoSans', fontSize=12, textColor=colors.white, alignment=1))
    styles.add(ParagraphStyle(name='CustomTableData', fontName='NotoSans', fontSize=12, textColor=colors.black, alignment=1))
    styles.add(ParagraphStyle(name='CustomFooter', fontName='NotoSans', fontSize=12, textColor=colors.black, spaceBefore=20))

    # Add title
    title = Paragraph(f'{title_text}', styles['CustomTitle'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Convert dataframe to table data
    table_data = [df.columns.tolist()] + df.values.tolist()

    # Style table header and data
    styled_table_data = []
    for i, row in enumerate(table_data):
        styled_row = []
        for cell in row:
            if i == 0:  # Header
                styled_row.append(Paragraph(str(cell), styles['CustomTableHeader']))
            else:
                styled_row.append(Paragraph(str(cell), styles['CustomTableData']))
        styled_table_data.append(styled_row)

    # Create a Table
    table = Table(styled_table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all cells
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 12))

    # Add notes with part of the text in red
    note_text = (
        f"備註：此為{date}抽籤結果，<font color='red'>不代表</font>{Taiwan_year:03d}年第{quarter}期最後停車名單。"
    )
    note = Paragraph(note_text, styles['CustomFooter'])
    elements.append(note)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def mask_name(name):
    return name[0] + '○' + name[2:] if len(name) > 1 else name

def get_quarter(year, month):
    if 1 <= month <= 3:
        return year, 2
    elif 4 <= month <= 6:
        return year, 3
    elif 7 <= month <= 9:
        return year, 4
    elif 10 <= month <= 12:
        return year + 1, 1
    else:
        raise ValueError("Month must be between 1 and 12")

# Streamlit 应用代码
today = datetime.today()
year, quarter = get_quarter(today.year, today.month)
Taiwan_year = year - 1911
current = f"{Taiwan_year}{quarter:02}"
document_text = generate_title(Taiwan_year, quarter)
st.title('停車位抽籤系統')

# 连接到数据库
conn = get_db_connection()
cursor = conn.cursor()
spaces_number = cursor.execute("SELECT COUNT(車位編號) FROM 停車位 WHERE 使用狀態 = '抽籤'").fetchone()[0]
participants_number = cursor.execute("SELECT COUNT(姓名代號) FROM 申請紀錄 WHERE 期別 = ? AND 身分註記 = '一般'", (current,)).fetchone()[0]
conn.close()

st.write(f"##### 本期停車位數量: {spaces_number}")
st.write(f"##### 本期停車位抽籤人數: {participants_number}")

# 使用 Streamlit 的会话状态来存储抽籤结果
if 'results_df' not in st.session_state:
    st.session_state['results_df'] = None
if 'waitlist_df' not in st.session_state:
    st.session_state['waitlist_df'] = None
if 'combined_df' not in st.session_state:
    st.session_state['combined_df'] = None

if st.button('進行抽籤'):
    with st.spinner('系統抽籤中，請稍候...'):
        time.sleep(5)
        results, waitlist, results_df, waitlist_df, combined_df = perform_lottery(current)
        st.session_state['results_df'] = results_df
        st.session_state['waitlist_df'] = waitlist_df
        st.session_state['combined_df'] = combined_df
        st.write('### 車位分配結果')
        st.dataframe(combined_df)
        insert_lottery_results(current, results, waitlist)

if st.session_state['combined_df'] is not None:
    if st.button('產生抽籤結果檔案'):
        pdf_file = convert_df_to_pdf(st.session_state['combined_df'])
        st.download_button(
            label="下載檔案",
            data=pdf_file,
            file_name=f"{document_text}.pdf",
            mime="application/pdf"
        )
