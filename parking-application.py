import streamlit as st
import threading
import time

# 用於控制操作是否已經執行的旗標
operation_in_progress = False

# 號誌物件來保護操作的互斥
operation_lock = threading.Lock()

def perform_operation():
    global operation_in_progress
    with operation_lock:
        if operation_in_progress:
            return False  # 如果已經有操作在進行，返回 False
        operation_in_progress = True
    
    try:
        # 執行需要進行的操作
        st.write("執行提交表單後的操作...")
        time.sleep(5)  # 模擬操作的耗時
        st.success("操作完成!")
        return True
    finally:
        with operation_lock:
            operation_in_progress = False

def main():
    st.title("表單提交範例")
    
    if st.button("提交表單"):
        if not perform_operation():
            st.warning("有操作正在進行，請稍後再試。")
    
if __name__ == "__main__":
    main()
