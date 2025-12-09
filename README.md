# 🔐 License Server - Hướng Dẫn Cài Đặt

## 📋 Mục lục
1. [Chạy Local](#chạy-local)
2. [Deploy lên Render.com](#deploy-lên-rendercom)
3. [Tích hợp Google Sheets](#tích-hợp-google-sheets)
4. [Cấu hình Client App](#cấu-hình-client-app)

---

## Chạy Local

```bash
cd license_server
pip install -r requirements.txt
python app.py
```

**Truy cập**: http://localhost:5000
**Tài khoản**: admin / admin123

---

## Deploy lên Render.com

### Bước 1: Push lên GitHub
```bash
cd license_server
git init
git add .
git commit -m "License server"
git remote add origin https://github.com/YOUR_USERNAME/license-server.git
git push -u origin main
```

### Bước 2: Tạo Web Service
1. Vào https://render.com → New → Web Service
2. Connect GitHub repo
3. Cấu hình:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`

### Bước 3: Environment Variables
```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=matkhau_cua_ban
SECRET_KEY=key_bi_mat_cua_ban
FLASK_SECRET=flask_secret_key
```

---

## Tích hợp Google Sheets

### Bước 1: Tạo Google Cloud Project
1. Vào https://console.cloud.google.com
2. Tạo Project mới
3. Tìm và Enable:
   - **Google Sheets API**
   - **Google Drive API**

### Bước 2: Tạo Service Account
1. Menu → IAM & Admin → Service Accounts
2. Bấm **Create Service Account**
3. Điền tên → Create
4. Bấm vào account vừa tạo → Keys → Add Key → Create new key
5. Chọn **JSON** → Create
6. Download file JSON

### Bước 3: Tạo Google Sheet
1. Tạo Google Sheet mới
2. Copy **Sheet ID** từ URL:
   ```
   https://docs.google.com/spreadsheets/d/[SHEET_ID_Ở_ĐÂY]/edit
   ```
3. Bấm **Share** → Thêm email service account (dạng `xxx@project.iam.gserviceaccount.com`)
4. Cho quyền **Editor**

### Bước 4: Cấu hình Environment Variables
```
USE_GOOGLE_SHEETS=true
GOOGLE_SHEET_ID=1abc123xyz...
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
```

> **Lưu ý**: Copy toàn bộ nội dung file JSON vào biến `GOOGLE_SERVICE_ACCOUNT_JSON`

---

## Cấu hình Client App

Tạo file `VideoFX_Tool/.license_config`:
```json
{"api_url": "https://your-server.onrender.com/api/validate"}
```

---

## Environment Variables

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `ADMIN_USERNAME` | admin | Tên đăng nhập |
| `ADMIN_PASSWORD` | admin123 | Mật khẩu |
| `SECRET_KEY` | VFX_SECRET_2024_THOTOOL | Key tạo license |
| `FLASK_SECRET` | (random) | Session key |
| `USE_GOOGLE_SHEETS` | false | Dùng Google Sheets |
| `GOOGLE_SHEET_ID` | | ID của Sheet |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | | JSON credentials |

---

## API Endpoints

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/api/validate?device_id=XXX` | GET | Validate license (public) |
| `/api/login` | POST | Đăng nhập |
| `/api/licenses` | GET/POST | List/Add licenses |
| `/api/licenses/<id>` | PUT/DELETE | Update/Delete |
| `/api/extend/<id>` | POST | Gia hạn |
