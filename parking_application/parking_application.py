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

# 指定 Google Drive 資料夾ID (請自行替換)
drive_folder_id = '你的Google_Drive資料夾ID'

lockfile_path = "/tmp/operation.lock"

########################################
# 下載 & 上傳資料庫檔案
########################################
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

########################################
# 時間/期別相關
########################################
def get_quarter(year, month):
    """
    輸入 西元年份 與 月份，傳回
    new_year, new_quarter
    其中 quarter = 1~4
    """
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
    """
    輸入民國年份與該期別，回傳前兩期(民國年+2位期別)字串
    """
    # quarter = 1~4
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

########################################
# perform_operation
########################################
def perform_operation(conn, cursor, unit, name, car_number, employee_id, special_needs,
                      contact_info, previous1, previous2, current, local_db_path, db_file_id):
    lock = FileLock(lockfile_path)
    try:
        lock.acquire(timeout=1)
        time.sleep(3)
        # submit_application若需上傳附件則返回 True，否則 False
        need_upload = submit_application(
            conn, cursor, unit, name, car_number, employee_id, special_needs,
            contact_info, previous1, previous2, current, local_db_path, db_file_id
        )
        return need_upload
    except TimeoutError:
        st.warning("有操作正在進行，請稍後再試，或聯絡秘書處大樓管理組(6395)。")
        return False
    finally:
        if lock.is_locked:
            lock.release()

########################################
# email 發送
########################################
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

########################################
# 提交申請核心邏輯
########################################
def submit_application(conn, cursor, unit, name, car_number, employee_id,
                       special_needs, contact_info, previous1, previous2,
                       current, local_db_path, db_file_id):
    """
    核心邏輯：
      1. 驗證輸入
      2. 插入/查詢資料表
      3. 判斷需不需要補件
      4. 需要補件就 return True，不需要就 return False
    """
    try:
        # 基本驗證
        if not unit or not name or not car_number or not employee_id or not special_needs or not contact_info:
            st.error('請填寫完整表單！')
            return False
        elif not re.match(r'^[A-Z0-9]+$', car_number):
            st.error('您填寫的車號欄位有誤，請調整後重新提交表單')
            return False
        elif not re.match(r'^[0-9]+$', employee_id):
            st.error('您填寫的員工編號有+U，請調整後重新提交表單')
            return False

        # 是否本期重覆申請
        cursor.execute('''
            SELECT 1 FROM 申請紀錄 WHERE 期別 = ? AND 姓名代號 = ?
        ''', (current, employee_id))
        existing_record = cursor.fetchone()
        if existing_record:
            st.error('您已經在本期提交過申請，請勿重複提交，如需修正申請資料請聯繫秘書處大樓管理組(分機:6395)!')
            return False

        # 各種邏輯
        if special_needs == '孕婦':
            status = get_pregnant_record_status(cursor, employee_id, previous1, previous2)

            if status == 'none':
                # 需上傳附件
                insert_apply(conn, cursor, unit, name, car_number, employee_id,
                             special_needs, contact_info, False, current, local_db_path, db_file_id)
                st.error('您為第一次孕婦申請，請將相關證明文件(如 :孕婦手冊、行照、駕照)補件上傳或電郵至example@taipower.com.tw')
                text = "您為第一次孕婦申請，請將相關證明文件(如 :孕婦手冊、行照、駕照)電郵回覆或於系統上傳。"
                subject_text = "本期停車補證明文件通知"
                send_email(employee_id, name, text, subject_text)
                return True  # <<-- 需要補件

            elif status == 'only_last_period':
                if has_approved_car_record(cursor, employee_id, car_number):
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 special_needs, contact_info, True, current, local_db_path, db_file_id)
                    insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                    st.success('本期"孕婦"身分停車申請成功')
                    text = "您有孕婦資格，本期停車申請成功，感謝您。"
                    subject_text = "本期停車申請成功通知"
                    send_email(employee_id, name, text, subject_text)
                    return False
                else:
                    # 需上傳附件
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 special_needs, contact_info, False, current, local_db_path, db_file_id)
                    st.error('這輛車為第一次申請，請將相關證明文件補件上傳或電郵至example@taipower.com.tw')
                    text = "您有孕婦資格，但是該車為第一次申請停車，請補相關證明文件。"
                    subject_text = "本期停車補證明文件通知"
                    send_email(employee_id, name, text, subject_text)
                    return True  # <<-- 需要補件

            else:
                # 已超過孕婦期限 => 轉一般
                if has_approved_car_record(cursor, employee_id, car_number):
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 '一般', contact_info, True, current, local_db_path, db_file_id)
                    st.success('您已經過了孕婦申請期限，系統自動將您轉為一般身分申請本期停車成功。')
                    text = "您已經過了孕婦申請期限，系統自動將您轉為一般停車申請，感謝您。"
                    subject_text = "本期停車申請成功通知"
                    send_email(employee_id, name, text, subject_text)
                    return False
                else:
                    # 需上傳附件
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 '一般', contact_info, False, current, local_db_path, db_file_id)
                    st.error('您已過孕婦期限，系統自動將您轉為一般身分申請本期停車，且此車為第一次申請，請補件上傳或電郵。')
                    text = "您已經過了孕婦申請期限，但該車為第一次申請停車，請補相關證明文件。"
                    subject_text = "本期停車補證明文件通知"
                    send_email(employee_id, name, text, subject_text)
                    return True  # <<-- 需要補件

        elif special_needs == '身心障礙':
            # 是否已有身心障礙申請紀錄
            cursor.execute("SELECT * FROM 申請紀錄 WHERE 姓名代號 = ? AND 身分註記 = ?",
                           (employee_id, '身心障礙'))
            disable_data = cursor.fetchone()
            if disable_data:
                if has_approved_car_record(cursor, employee_id, car_number):
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 special_needs, contact_info, True, current, local_db_path, db_file_id)
                    insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                    st.success('本期"身心障礙"身分停車申請成功')
                    text = "您有身心障礙資格，本期停車申請成功，感謝您。"
                    subject_text = "本期停車申請成功通知"
                    send_email(employee_id, name, text, subject_text)
                    return False
                else:
                    # 需上傳附件
                    insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                 special_needs, contact_info, False, current, local_db_path, db_file_id)
                    st.error('這輛車為第一次申請，請將相關證明文件補件上傳或電郵至example@taipower.com.tw')
                    text = "您有身心障礙資格，但是該車為第一次申請停車，請補相關證明文件。"
                    subject_text = "本期停車補證明文件通知"
                    send_email(employee_id, name, text, subject_text)
                    return True
            else:
                # 需上傳附件
                insert_apply(conn, cursor, unit, name, car_number, employee_id,
                             special_needs, contact_info, False, current, local_db_path, db_file_id)
                st.error('您為第一次身心障礙申請，請將身心障礙證明、行照、駕照等補件上傳或電郵!')
                text = "您為第一次身心障礙申請，請將相關證明文件補件上傳或電郵。"
                subject_text = "本期停車補證明文件通知"
                send_email(employee_id, name, text, subject_text)
                return True

        else:
            # 一般
            cursor.execute("""
                SELECT * FROM 抽籤繳費
                WHERE 姓名代號 = ? AND 期別 = ? AND (繳費狀態 = '已繳費' OR 繳費狀態 = '轉讓')
            """, (employee_id, previous1))
            existing_data = cursor.fetchone()

            cursor.execute("""
                SELECT * FROM 申請紀錄
                WHERE 姓名代號 = ? AND 身分註記 in (?,?) AND 期別 = ?
            """, (employee_id, '一般', '保障', previous1))
            existing_application_data = cursor.fetchone()

            # 若上一期已確定停車 -> 不得申請
            if existing_data and existing_application_data:
                st.error('您上期已確認停車，請您下期再來申請停車位!')
                return False
            else:
                # 檢查是否連兩期都未抽中 => 保障
                if check_user_eligibility(employee_id, conn, cursor, previous1, previous2):
                    if has_approved_car_record(cursor, employee_id, car_number):
                        insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                     '保障', contact_info, True, current, local_db_path, db_file_id)
                        insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                        st.success('由於您前兩期申請停車都未抽籤，本期獲得保障資格!')
                        text = "您連續兩期都有申請且都未中籤，本期獲得保障車位。"
                        subject_text = "本期停車抽籤申請成功並獲得保障車位"
                        send_email(employee_id, name, text, subject_text)
                        return False
                    else:
                        # 需上傳附件
                        insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                     '保障', contact_info, False, current, local_db_path, db_file_id)
                        st.error('您前兩期都未中籤，本期獲得保障資格，但此車為第一次申請，請補件上傳或電郵。')
                        text = "您連續兩期都有申請停車，且都未中籤；本期獲得保障車位，但該車為第一次申請。請補證明文件。"
                        subject_text = "本期停車抽籤申請補證明文件通知"
                        send_email(employee_id, name, text, subject_text)
                        return True
                else:
                    # 檢查是否上期曾是孕婦
                    status = get_pregnant_record_status(cursor, employee_id, previous1, previous2)
                    if status == 'only_last_period':
                        if has_approved_car_record(cursor, employee_id, car_number):
                            insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                         '孕婦', contact_info, True, current, local_db_path, db_file_id)
                            insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id)
                            st.success('由於您上期申請孕婦資格成功，本期將自動替換為孕婦身分申請!')
                            text = "您上期孕婦申請成功，本期自動帶入孕婦身份，獲得保障車位。"
                            subject_text = "本期停車抽籤申請成功並改為孕婦身份"
                            send_email(employee_id, name, text, subject_text)
                            return False
                        else:
                            # 需上傳附件
                            insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                         '孕婦', contact_info, False, current, local_db_path, db_file_id)
                            st.error('您上期孕婦資格成功，但此車為第一次申請，請補件上傳或電郵。')
                            text = "您上期孕婦申請成功，但該車為第一次申請，請補證明文件。"
                            subject_text = "本期停車抽籤申請補證明文件通知"
                            send_email(employee_id, name, text, subject_text)
                            return True
                    else:
                        # 一般申請
                        if has_approved_car_record(cursor, employee_id, car_number):
                            insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                         special_needs, contact_info, True, current, local_db_path, db_file_id)
                            st.success('本期一般車位申請成功!')
                            text = "本期您一般身分停車抽籤申請成功，感謝您。"
                            subject_text = "本期停車抽籤申請成功通知"
                            send_email(employee_id, name, text, subject_text)
                            return False
                        else:
                            # 需上傳附件
                            insert_apply(conn, cursor, unit, name, car_number, employee_id,
                                         special_needs, contact_info, False, current, local_db_path, db_file_id)
                            st.error('此輛車為第一次申請，請補件上傳或電郵!')
                            text = "您為第一次申請停車位，請將相關證明文件補件上傳或電郵。"
                            subject_text = "本期停車抽籤申請補證明文件通知"
                            send_email(employee_id, name, text, subject_text)
                            return True

    except:
        st.warning("有操作正在進行，請稍後再試，或聯絡秘書處大樓管理組(6395)。")
        return False

########################################
# 寫入資料庫：申請紀錄
########################################
def insert_apply(conn, cursor, unit, name, car_number, employee_id, special_needs,
                 contact_info, car_bind, current, local_db_path, db_file_id):
    current_date = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('''
    INSERT INTO 申請紀錄 (日期,期別,姓名代號,姓名,單位,車牌號碼,聯絡電話,身分註記,車牌綁定)
    VALUES (?,?,?,?,?,?,?,?,?)
    ''', (current_date, current, employee_id, name, unit,
          car_number, contact_info, special_needs, car_bind))
    conn.commit()
    upload_db(local_db_path, db_file_id)

########################################
# 判斷是否連續兩期未中籤
########################################
def check_user_eligibility(employee_id, conn, cursor, previous1, previous2):
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

########################################
# 判斷該車號是否已核備
########################################
def has_approved_car_record(cursor, employee_id, car_number):
    cursor.execute("SELECT * FROM 使用者車牌 WHERE 姓名代號 = ? AND 車牌號碼 = ?", (employee_id, car_number))
    return cursor.fetchone() is not None

########################################
# 寫入資料庫：抽籤繳費
########################################
def insert_parking_fee(conn, cursor, current, employee_id, local_db_path, db_file_id):
    insert_query = """
    INSERT INTO 抽籤繳費 (期別,姓名代號,繳費狀態)
    VALUES (?,?,'未繳費')
    """
    cursor.execute(insert_query, (current, employee_id))
    conn.commit()
    upload_db(local_db_path, db_file_id)

########################################
# 判斷上期/前期是否為孕婦
########################################
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

########################################
# Streamlit 主程式
########################################
def main():
    # 取得民國年的期別
    today = datetime.today()
    west_year, quarter = get_quarter(today.year, today.month)
    Taiwan_year = west_year - 1911
    current = f"{Taiwan_year}{quarter:02}"
    previous1, previous2 = previous_quarters(Taiwan_year, quarter)

    st.title('停車抽籤申請表單')

    # Google Drive上資料庫ID
    db_file_id = '1_TArAUZyzzZuLX3y320VpytfBlaoUGBB'
    local_db_path = '/tmp/test.db'
    download_db(db_file_id, local_db_path)

    conn = sqlite3.connect(local_db_path)
    cursor = conn.cursor()

    # 初始化 Session State
    if 'need_upload' not in st.session_state:
        st.session_state['need_upload'] = False

    # 若不需要上傳附件，就顯示「主要表單」；否則顯示「附件上傳」
    if not st.session_state['need_upload']:
        # ---- 第一階段：主要表單 ----
        with st.form(key='application_form'):
            unit = st.selectbox('(1)請問您所屬單位?', ['秘書處', '公眾服務處'])
            name = st.text_input('(2)請問您的大名?')
            car_number_prefix = st.text_input('(3-1)車牌前半段').upper()
            car_number_suffix = st.text_input('(3-2)車牌後半段').upper()
            car_number = car_number_prefix + car_number_suffix
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
                # 如果需要補件 => 下一階段
                if need_upload:
                    # 把後續命名需要用到的資料存進session
                    st.session_state['need_upload'] = True
                    st.session_state['unit'] = unit
                    st.session_state['name'] = name
                    st.experimental_rerun()

    else:
        # ---- 第二階段：附件上傳 ----
        st.warning('請上傳相關證明文件（可一次上傳多檔）：')
        uploaded_files = st.file_uploader(
            "上傳附件檔案（可多選）", 
            type=['jpg', 'jpeg', 'png', 'pdf'], 
            accept_multiple_files=True
        )

        # 為了避免跟form衝突，此處直接使用button
        if uploaded_files:
            if st.button('確認上傳'):
                for idx, uploaded_file in enumerate(uploaded_files, start=1):
                    # 若只上傳一個檔案，就命名「unit_name.副檔名」
                    # 若多於一個檔案，就於尾端加編號 _1, _2, ...
                    file_ext = uploaded_file.name.split('.')[-1]
                    filename = f"{st.session_state['unit']}_{st.session_state['name']}"
                    if len(uploaded_files) > 1:
                        filename += f"_{idx}"
                    filename += f".{file_ext}"

                    file_metadata = {
                        'name': filename,
                        'parents': [drive_folder_id]
                    }
                    media = MediaIoBaseUpload(uploaded_file, mimetype=uploaded_file.type, resumable=True)
                    service.files().create(body=file_metadata, media_body=media, fields='id').execute()

                st.success("所有附件已成功上傳到 Google Drive！")
                st.balloons()
                # 上傳完後，重置 need_upload 狀態
                st.session_state['need_upload'] = False

    cursor.close()
    conn.close()

if __name__ == '__main__':
    main()

