import streamlit as st

st.title("Upload-Test")

file = st.file_uploader("ZIP auswählen", type=["zip"])

if file is not None:
    st.success(f"Empfangen: {file.name}, {file.size} Bytes")