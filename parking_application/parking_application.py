import streamlit as st
import sqlite3
import os
import re
import io
import time
import smtplib
from filelock import FileLock
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload, MediaIoBaseUpload

# 建立 Google Drive API 連線
creds = Credentials.from_service_account_info(st.secrets["google_drive"])
service = build('drive', 'v3', credentials=creds)

# 指定「主資料夾」ID（Service Account 可寫入）
drive_folder_id = '1RlnOdNPo5hWDz-ccKCR8R-ef1Gw2B3US'

# 上傳/下載資料庫用的檔案鎖
lockfile_path = "/tmp/operation.lock"


####################################################################
# 資料庫讀寫函式
####################################################################
def download_db(file_id, destination):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(destination, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

def upload_db(source, file_id):
    file_metadata = {'name': 'test.db'}
    media = MediaFileUpload(source, mimetype='application/x-sqlite3')
    service.files().update(fileId=file_id, media_body=media).execute()

####################################################################
# 計算期別
####################################################################
def get_quarter(year, month):
    if 1 <= month <= 3:
        quarter = 2
    elif 4 <= month <= 6:
        quarter = 3
    elif 7 <= month <= 9:
        quarter = 4
    elif 10 <= month <= 12:
        year += 1
        quarter = 1
    else:
        raise ValueError("Month must be between 1 and 12")
    return year, quarter

def previous_quarters(year, quarter):
    if quarter == 1:
        previous1_year, previous1_quarter = year - 1, 4
        previous2_year, previous2_quarter = year - 1, 3
    elif quarter == 2:
        previous1_year, previous1_quarter = year, 1
        previous2_year, previous2_quarter = year - 1, 4
    elif quarter == 3:
        previous1_year, previous1_quarter = year, 2
        previous2_year, previous2_quarter = year, 1
    elif quarter == 4:
        previous1_year, previous1_quarter = year, 3
        previous2_year, previous2_quarter = year, 2
    return (f"{previous1_year}{previous1_quarter:02}", f"{previous2_year}{previous2_quarter:02}")

####################################################################
# email 發送
####################################################################
def send_email(employee_id, name, text, subject_text):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    smtp_server = "smtp.gmail.com"
    smtp_port = 465

    subject = subject_text
    body = f"{name}您好,\n{text}\n秘書處 大樓管理組 敬上\n聯絡電話:(02)2366-6395"

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = f"u{employee_id}@taipower.com.tw"
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, f"u{employee_id}@taipower.com.tw", message.as_string())
        server.close()
        return "郵件已發送成功！"
    except Exception as e:
        return f"發送郵件時發生錯誤: {e}"

####################################################################
# 資料庫操作：插入申請紀錄 & 繳費紀錄
####################################################################
def insert_apply(conn, cursor, unit, name, car_number, employee_id,
                 special_needs, contact_info, car_bind, current,
                 local_db_path, db_file_id):
    current_date = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('''
    INSERT INTO 申請紀錄 (日期,期別,姓名代號,姓名,單位,車牌號碼,聯絡電話,身分註記,車牌綁定)
    VALUES (?,?,?,?,?,?,?,?,?)
    ''', (current_date, current, employee_id, name, unit,
          car_number, contact_info, special_needs, car_bind))
    conn.commit()
    upload_db(local_db_path, db_file_id)

def insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id):
    insert_query = """
    INSERT INTO 抽籤繳費 (期別,姓名代號,繳費狀態)
    VALUES (?,?,'未繳費')
    """
    cursor.execute(insert_query, (current, employee_id))
    conn.commit()
    upload_db(local_db_path, db_file_id)

####################################################################
# 資料庫邏輯判斷
####################################################################
def check_user_eligibility(employee_id, conn, cursor, previous1, previous2):
    # 判斷是否連兩期 '未繳費' => 未抽中
    cursor.execute('''
        SELECT COUNT(*)
        FROM 抽籤繳費
        WHERE 姓名代號 = ? AND 期別 = ? AND 繳費狀態 = '未繳費'
    ''', (employee_id, previous2))
    unpaid_before_last_period = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(*)
        FROM 抽籤繳費
        WHERE 姓名代號 = ? AND 期別 = ? AND 繳費狀態 = '未繳費'
    ''', (employee_id, previous1))
    unpaid_last_period = cursor.fetchone()[0]

    return unpaid_before_last_period > 0 and unpaid_last_period > 0

def has_approved_car_record(cursor, employee_id, car_number):
    cursor.execute("SELECT * FROM 使用者車牌 WHERE 姓名代號 = ? AND 車牌號碼 = ?", (employee_id, car_number))
    return cursor.fetchone() is not None

def get_pregnant_record_status(cursor, employee_id, last_period, before_last_period):
    cursor.execute('''
        SELECT 期別 FROM 申請紀錄
        WHERE 姓名代號 = ? AND 期別 IN (?, ?) AND 身分註記 = ?
    ''', (employee_id, last_period, before_last_period, '孕婦'))
    records = cursor.fetchall()
    periods = [record[0] for record in records]
    if last_period in periods and before_last_period in periods:
        return "both"
    elif last_period in periods:
        return "only_last_period"
    elif before_last_period in periods:
        return "only_before_last_period"
    else:
        return "none"

####################################################################
# 補件時的檔案上傳資料夾管理
####################################################################
def get_or_create_subfolder(service, parent_folder_id, subfolder_name):
    query = (
        f"name = '{subfolder_name}' "
        f"and '{parent_folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    subfolders = response.get('files', [])
    if subfolders:
        return subfolders[0]['id']
    else:
        folder_metadata = {
            'name': subfolder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        return folder['id']

####################################################################
# 主邏輯：表單送出 => 判斷 => 若需補件 => 暫存; 若不需補件 => 直接插DB & 寄信
####################################################################
def submit_application(conn, cursor, unit, name, car_number, employee_id,
                       special_needs, contact_info, previous1, previous2,
                       current, local_db_path, db_file_id):
    """
    1) 若不需要上傳附件 => 直接在這裡插入資料庫 / 寄信 / 回傳 False
    2) 若需要上傳附件 => 不做插入或寄信，只在 st.session_state['pending_insert'] 裝載所有資訊
       並回傳 True => 讓主程式進入附件上傳頁面
    """
    # 基本驗證
    if not unit or not name or not car_number or not employee_id or not special_needs or not contact_info:
        st.error('請填寫完整表單！')
        return False
    if not re.match(r'^[A-Z0-9]+$', car_number):
        st.error('您填寫的車號欄位有誤，請調整後重新提交表單')
        return False
    if not re.match(r'^[0-9]+$', employee_id):
        st.error('您填寫的員工編號並非純數字(如:123456)，請調整後重新提交表單')
        return False

    # 是否本期重覆申請
    cursor.execute('SELECT 1 FROM 申請紀錄 WHERE 期別 = ? AND 姓名代號 = ?', (current, employee_id))
    existing_record = cursor.fetchone()
    if existing_record:
        st.error('您已經在本期提交過申請，請勿重複提交，如需修正請聯繫管理組(6395)!')
        return False

    # 根據邏輯判斷
    if special_needs == '孕婦':
        status = get_pregnant_record_status(cursor, employee_id, previous1, previous2)

        if status == 'none':
            # ---- 需要補件，但「尚未」插DB或寄信 ----
            st.session_state['pending_insert'] = {
                "unit": unit,
                "name": name,
                "car_number": car_number,
                "employee_id": employee_id,
                "special_needs": special_needs,  # '孕婦'
                "contact_info": contact_info,
                "car_bind": False,      # 第一次申請 => False
                "current": current,
                "should_insert_parking_fee": False,   # 還未給予車位
                "email_text": "您為第一次孕婦申請，請上傳孕婦手冊、行照、駕照等證明文件。",
                "email_subject": "本期停車補證明文件通知",
                "success_message": "本期『孕婦申請』已完成，感謝您補件。"  
            }
            return True

        elif status == 'only_last_period':
            if has_approved_car_record(cursor, employee_id, car_number):
                # 直接插DB & 寄信
                insert_apply(conn, cursor, unit, name, car_number, employee_id,
                             special_needs, contact_info, True, current, local_db_path, db_file_id)
                insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                st.success('本期"孕婦"身分停車申請成功')
                text = "您有孕婦資格，本期停車申請成功，感謝您。"
                subject_text = "本期停車申請成功通知"
                send_email(employee_id, name, text, subject_text)
                return False
            else:
                # 需要補件 => 暫存
                st.session_state['pending_insert'] = {
                    "unit": unit,
                    "name": name,
                    "car_number": car_number,
                    "employee_id": employee_id,
                    "special_needs": special_needs,  # '孕婦'
                    "contact_info": contact_info,
                    "car_bind": False,
                    "current": current,
                    "should_insert_parking_fee": True, 
                    "email_text": "您有孕婦資格，但此車為第一次申請，請上傳孕婦資格證明文件及車輛文件。",
                    "email_subject": "本期停車補證明文件通知",
                    "success_message": "本期『孕婦申請』已完成，感謝您補件。系統已為您預留孕婦車位。"
                }
                return True

        else:
            # 已過孕婦資格 => 轉一般
            if has_approved_car_record(cursor, employee_id, car_number):
                # 無需補件
                insert_apply(conn, cursor, unit, name, car_number, employee_id,
                             '一般', contact_info, True, current, local_db_path, db_file_id)
                st.success('您已過孕婦申請期，系統自動改為一般申請成功。')
                text = "您已過孕婦申請期，系統自動將您轉為一般申請，感謝您。"
                subject_text = "本期停車申請成功通知"
                send_email(employee_id, name, text, subject_text)
                return False
            else:
                # 需要補件 => 暫存
                st.session_state['pending_insert'] = {
                    "unit": unit,
                    "name": name,
                    "car_number": car_number,
                    "employee_id": employee_id,
                    "special_needs": '一般',
                    "contact_info": contact_info,
                    "car_bind": False,
                    "current": current,
                    "should_insert_parking_fee": False, 
                    "email_text": "您已過孕婦申請期，但此車為第一次申請一般停車，請上傳車輛證明文件。",
                    "email_subject": "本期停車補證明文件通知",
                    "success_message": "本期『一般申請』已完成，感謝您補件。"
                }
                return True

    elif special_needs == '身心障礙':
        # 看之前是否有身障紀錄
        cursor.execute("SELECT * FROM 申請紀錄 WHERE 姓名代號=? AND 身分註記='身心障礙'", (employee_id,))
        disable_data = cursor.fetchone()
        if disable_data:
            if has_approved_car_record(cursor, employee_id, car_number):
                insert_apply(conn, cursor, unit, name, car_number, employee_id,
                             special_needs, contact_info, True, current, local_db_path, db_file_id)
                insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                st.success('本期"身心障礙"停車申請成功')
                text = "您有身心障礙資格，本期停車申請成功。"
                subject_text = "本期停車申請成功通知"
                send_email(employee_id, name, text, subject_text)
                return False
            else:
                # 需要補件 => 暫存
                st.session_state['pending_insert'] = {
                    "unit": unit,
                    "name": name,
                    "car_number": car_number,
                    "employee_id": employee_id,
                    "special_needs": special_needs,  # '身心障礙'
                    "contact_info": contact_info,
                    "car_bind": False,
                    "current": current,
                    "should_insert_parking_fee": True,
                    "email_text": "您有身心障礙資格，但此車為第一次申請，請上傳身障證明與車輛證明文件。",
                    "email_subject": "本期停車補證明文件通知",
                    "success_message": "本期『身心障礙』已完成，感謝您補件。系統已為您預留身障車位。"
                }
                return True
        else:
            # 第一次身障申請 => 需補件
            st.session_state['pending_insert'] = {
                "unit": unit,
                "name": name,
                "car_number": car_number,
                "employee_id": employee_id,
                "special_needs": special_needs,  # '身心障礙'
                "contact_info": contact_info,
                "car_bind": False,
                "current": current,
                "should_insert_parking_fee": False,
                "email_text": "您為第一次身心障礙申請，請上傳身障證明、行照、駕照等文件。",
                "email_subject": "本期停車補證明文件通知",
                "success_message": "本期『身心障礙申請』已完成，感謝您補件。"
            }
            return True

    else:
        # 一般
        cursor.execute("""
            SELECT * FROM 抽籤繳費
            WHERE 姓名代號 = ?
              AND 期別 = ?
              AND (繳費狀態 = '已繳費' OR 繳費狀態 = '轉讓')
        """, (employee_id, previous1))
        existing_data = cursor.fetchone()

        cursor.execute("""
            SELECT * FROM 申請紀錄
            WHERE 姓名代號 = ?
              AND 身分註記 in (?,?)
              AND 期別 = ?
        """, (employee_id, '一般', '保障', previous1))
        existing_application_data = cursor.fetchone()

        # 上期已確定停車 => 不得申請
        if existing_data and existing_application_data:
            st.error('您上期已確認停車，請下期再申請停車位!')
            return False
        else:
            # 是否連兩期都未抽中 => 保障
            if check_user_eligibility(employee_id, conn, cursor, previous1, previous2):
                if has_approved_car_record(cursor, employee_id, car_number):
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 '保障', contact_info, True, current, local_db_path, db_file_id)
                    insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                    st.success('您前兩期都未抽中，本期獲得保障車位!')
                    text = "您連續兩期都有申請，且都未中籤，本期獲得保障車位。"
                    subject_text = "本期停車申請成功並獲得保障車位"
                    send_email(employee_id, name, text, subject_text)
                    return False
                else:
                    # 需要補件 => 暫存
                    st.session_state['pending_insert'] = {
                        "unit": unit,
                        "name": name,
                        "car_number": car_number,
                        "employee_id": employee_id,
                        "special_needs": '保障',
                        "contact_info": contact_info,
                        "car_bind": False,
                        "current": current,
                        "should_insert_parking_fee": True,
                        "email_text": "您前兩期都未中籤，本期享保障車位，但此車為第一次申請。請上傳車輛證明文件。",
                        "email_subject": "本期停車補證明文件通知",
                        "success_message": "本期『保障車位申請』已完成，感謝您補件。系統已為您預留保障車位。"
                    }
                    return True
            else:
                # 檢查是否上期曾是孕婦 => 可能自動帶入孕婦
                status = get_pregnant_record_status(cursor, employee_id, previous1, previous2)
                if status == 'only_last_period':
                    if has_approved_car_record(cursor, employee_id, car_number):
                        insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                     '孕婦', contact_info, True, current, local_db_path, db_file_id)
                        insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                        st.success('您上期孕婦申請成功，本期自動帶入孕婦車位!')
                        text = "您上期孕婦申請成功，本期自動帶入孕婦身份，獲得保障。"
                        subject_text = "本期停車申請成功並改為孕婦身份"
                        send_email(employee_id, name, text, subject_text)
                        return False
                    else:
                        # 需要補件 => 暫存
                        st.session_state['pending_insert'] = {
                            "unit": unit,
                            "name": name,
                            "car_number": car_number,
                            "employee_id": employee_id,
                            "special_needs": '孕婦',
                            "contact_info": contact_info,
                            "car_bind": False,
                            "current": current,
                            "should_insert_parking_fee": True,
                            "email_text": "您上期孕婦申請成功，但此車為第一次申請，請上傳孕婦/車輛證明文件。",
                            "email_subject": "本期停車補證明文件通知",
                            "success_message": "本期『孕婦申請』已完成，感謝您補件。"
                        }
                        return True
                else:
                    # 純一般申請
                    if has_approved_car_record(cursor, employee_id, car_number):
                        # 直接成功
                        insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                     special_needs, contact_info, True, current, local_db_path, db_file_id)
                        st.success('本期一般車位申請成功!')
                        text = "本期您一般身分停車抽籤申請成功，感謝您。"
                        subject_text = "本期停車抽籤申請成功通知"
                        send_email(employee_id, name, text, subject_text)
                        return False
                    else:
                        # 需要補件 => 暫存
                        st.session_state['pending_insert'] = {
                            "unit": unit,
                            "name": name,
                            "car_number": car_number,
                            "employee_id": employee_id,
                            "special_needs": special_needs,
                            "contact_info": contact_info,
                            "car_bind": False,
                            "current": current,
                            "should_insert_parking_fee": False,
                            "email_text": "您為第一次申請一般車位，請上傳車輛證明文件。",
                            "email_subject": "本期停車補證明文件通知",
                            "success_message": "本期『一般申請』已完成，感謝您補件。"
                        }
                        return True

####################################################################
# 執行主要邏輯：加檔案鎖 & 呼叫 submit_application
####################################################################
def perform_operation(conn, cursor, unit, name, car_number, employee_id, special_needs,
                      contact_info, previous1, previous2, current, local_db_path, db_file_id):
    lock = FileLock(lockfile_path)
    try:
        lock.acquire(timeout=1)
        time.sleep(3)
        need_upload = submit_application(
            conn, cursor, unit, name, car_number, employee_id, special_needs,
            contact_info, previous1, previous2, current, local_db_path, db_file_id
        )
        return need_upload
    except TimeoutError:
        st.warning("有操作正在進行，請稍後再試，或聯絡管理組(6395)。")
        return False
    finally:
        if lock.is_locked:
            lock.release()

####################################################################
# Streamlit 主程式
####################################################################
def main():
    # 取得民國年期別
    today = datetime.today()
    west_year, quarter = get_quarter(today.year, today.month)
    Taiwan_year = west_year - 1911
    current = f"{Taiwan_year}{quarter:02}"
    previous1, previous2 = previous_quarters(Taiwan_year, quarter)
    title = f"{Taiwan_year}年第{quarter}期台灣電力股份有限公司總管理處停車位申請"

    st.set_page_config(layout="wide", page_title=title)
    st.title(title)
    st.markdown("有申請過停車的同仁不需提供證明文件，若為第一次申請系統會提示需要上傳證明文件檔案，確認上傳後即完成本期停車申請。員工申請停車位所檢具之證明文件檔案，經秘書處審核後即刪除，並填報「個人資料刪除、銷燬紀錄表」備查，以符合個人資料保護法相關規定。")

    # 下載資料庫
    db_file_id = '1_TArAUZyzzZuLX3y320VpytfBlaoUGBB'
    local_db_path = '/tmp/test.db'
    download_db(db_file_id, local_db_path)

    conn = sqlite3.connect(local_db_path)
    cursor = conn.cursor()

    # 若 session_state 裡沒子資料夾ID => 自動建立/取得
    if 'subfolder_id' not in st.session_state:
        st.session_state['subfolder_id'] = get_or_create_subfolder(service, drive_folder_id, title)

    # 狀態初始化
    if 'need_upload' not in st.session_state:
        st.session_state['need_upload'] = False
    # 用來暫存「要插入 DB 及寄信」的資訊
    if 'pending_insert' not in st.session_state:
        st.session_state['pending_insert'] = {}
    # 顯示在附件頁面的提醒訊息
    if 'upload_prompt' not in st.session_state:
        st.session_state['upload_prompt'] = ""

    # ★★★ 第一階段：表單填寫 ★★★
    if not st.session_state['need_upload']:
        with st.form(key='application_form'):
        unit = st.selectbox('(1)請問您所屬單位?', ['秘書處', '公眾服務處'])
        name = st.text_input('(2)請問您的大名?')
        
        # 產生一個容器
        with st.container() as car_block:
            # 區塊開頭：顯示一段帶邊框的 <div>
            car_block.markdown(
                """
                <div style='border: 1px solid #CCC; padding: 15px; border-radius: 5px; margin-bottom: 1rem'>
                  <p><strong>備註：</strong>請將車號分成前後半段填寫(如：ABC-1234，就拆成前半段 ABC，後半段 1234)</p>
                """,
                unsafe_allow_html=True
            )
    
            # 放入兩個 text_input 欄位（Streamlit 元件會自動接在這個 Markdown 之後）
            car_number_prefix = car_block.text_input("(3-1) 車牌前半段（'-' 前）").upper()
            car_number_suffix = car_block.text_input("(3-2) 車牌後半段（'-' 後）").upper()
    
            # 區塊結尾：關閉 <div>
            car_block.markdown("</div>", unsafe_allow_html=True)

        employee_id = st.text_input('(4)員工編號(不+U)')
        special_needs = st.selectbox('(5)是否有特殊需求？', ['一般', '孕婦', '身心障礙'])
        contact_info = st.text_input('(6)您的公務聯絡方式?')
    
        st.warning("請確認填寫資料完全無誤後，再點擊'提交'")
        submit_button = st.form_submit_button(label='提交')
    
        if submit_button:
            with st.spinner('資料驗證中，請稍候...'):
                need_upload = perform_operation(
                    conn, cursor, unit, name, car_number, employee_id,
                    special_needs, contact_info, previous1, previous2,
                    current, local_db_path, db_file_id
                )
                if need_upload:
                    # 代表需要上傳附件 => 進入第二階段
                    st.session_state['need_upload'] = True
                    # 這裡可以存「提示訊息」給第二階段顯示
                    st.session_state['upload_prompt'] = (
                        "請上傳相關證明文件（可一次上傳多檔），再按下確認完成申請。"
                    )
                    st.experimental_rerun()

    # ★★★ 第二階段：附件上傳 + 真的插入DB & 寄信 ★★★
    else:
        # 如果有提示訊息，就先顯示
        if st.session_state['upload_prompt']:
            st.error(st.session_state['upload_prompt'])

        st.warning("請上傳相關證明文件（可一次上傳多檔）：")
        uploaded_files = st.file_uploader(
            "上傳附件檔案（可多選）", type=['jpg', 'jpeg', 'png', 'pdf'], accept_multiple_files=True
        )

        if uploaded_files:
            if st.button('確認上傳'):
                # 1) 先把附件全部上傳到對應子資料夾
                for idx, uploaded_file in enumerate(uploaded_files, start=1):
                    file_ext = uploaded_file.name.split('.')[-1]
                    filename = f"{st.session_state['pending_insert'].get('unit','')}_"
                    filename += f"{st.session_state['pending_insert'].get('name','')}"

                    if len(uploaded_files) > 1:
                        filename += f"_{idx}"
                    filename += f".{file_ext}"

                    file_metadata = {
                        'name': filename,
                        'parents': [st.session_state['subfolder_id']]
                    }
                    media = MediaIoBaseUpload(uploaded_file, mimetype=uploaded_file.type, resumable=False)
                    service.files().create(body=file_metadata, media_body=media, fields='id').execute()

                # 2) 上傳完附件後，再真正插入資料 & 寄信
                pending = st.session_state['pending_insert']
                if pending:
                    insert_apply(
                        conn, cursor,
                        pending['unit'], pending['name'], pending['car_number'],
                        pending['employee_id'], pending['special_needs'],
                        pending['contact_info'], pending['car_bind'],
                        pending['current'], local_db_path, db_file_id
                    )
                    if pending['should_insert_parking_fee']:
                        insert_parking_fee(conn, cursor, pending['current'], pending['employee_id'],
                                           local_db_path, db_file_id)

                    # 寄信
                    send_email(
                        pending['employee_id'],
                        pending['name'],
                        pending['email_text'],
                        pending['email_subject']
                    )

                    # 顯示成功訊息
                    st.success(pending['success_message'])

                # 3) 清理狀態
                st.session_state['need_upload'] = False
                st.session_state['upload_prompt'] = ""
                st.session_state['pending_insert'] = {}

                st.balloons()

    cursor.close()
    conn.close()

if __name__ == '__main__':
    main()



