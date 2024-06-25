import streamlit as st
from filelock import FileLock
import time

# 鎖文件的路徑
lockfile_path = "/tmp/operation.lock"

def perform_operation():
    lock = FileLock(lockfile_path)
    try:
        lock.acquire(timeout=1)
        st.write("執行提交表單後的操作...")
        time.sleep(5)  # 模擬操作的耗時
        st.success("操作完成!")
        return True
    except TimeoutError:
        st.warning("有操作正在進行，請稍後再試。")
        return False
    finally:
        if lock.is_locked:
            lock.release()

def main():
    st.title("表單提交範例")

    if st.button("提交表單"):
        perform_operation()

if __name__ == "__main__":
    main()
