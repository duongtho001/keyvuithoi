# License Server Dist

Thư mục này sẵn sàng để upload lên hosting.

## Files
- `app.py` - Flask server
- `requirements.txt` - Dependencies
- `Procfile` - Cho Render/Heroku
- `runtime.txt` - Python version
- `README.md` - Hướng dẫn

## Deploy nhanh lên Render.com

1. Tạo repo GitHub mới
2. Upload toàn bộ thư mục này
3. Vào render.com → New → Web Service
4. Connect repo → Deploy

## Environment Variables cần thiết
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_password
SECRET_KEY=your_secret
FLASK_SECRET=flask_session_key
```

## Dùng Google Sheets (tùy chọn)
```
USE_GOOGLE_SHEETS=true
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account"...}
```
