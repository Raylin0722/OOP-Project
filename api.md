# API Documentation
## Account

本文件整理目前帳號系統相關 API，包含註冊、信箱驗證、登入、登出、取得目前使用者，以及忘記密碼流程。

### 基本資訊

後端 API base URL：

```text
http://127.0.0.1:8000/api
```

所有 API 都使用 JSON 傳遞資料：

```http
Content-Type: application/json
```

前端呼叫時若需要保留登入狀態，需要帶 cookie：

```js
fetch(url, {
  credentials: 'include',
})
```

回傳的使用者資料格式通常如下：

```json
{
  "id": 1,
  "username": "PlayerOne",
  "email": "player@example.com",
  "email_verified": true,
  "nickname": "Player",
  "total_score": 0,
  "win_rate": 0.0
}
```

錯誤回傳格式通常如下：

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "login failed."
  }
}
```

### 1. 註冊帳號

```http
POST /api/auth/register/
```

#### 用途

建立新帳號，並寄出信箱驗證碼。

註冊成功後，帳號會先建立為未啟用狀態：

```text
email_verified = false
```

使用者必須完成信箱驗證後才能登入。

#### Request Body

```json
{
  "username": "PlayerOne",
  "nickname": "Player",
  "email": "player@example.com",
  "password": "password123",
  "password_confirm": "password123"
}
```

#### 參數說明

| 參數 | 必填 | 說明 |
|---|---:|---|
| `username` | 是 | 使用者帳號。大小寫敏感，因此 `Ray` 和 `ray` 是不同帳號。 |
| `nickname` | 否 | 遊戲中顯示名稱。如果沒有填，後端會使用 `username` 當作 nickname。 |
| `email` | 是 | 使用者信箱。大小寫不敏感，後端會轉成小寫儲存。 |
| `password` | 是 | 密碼，至少 8 個字元。 |
| `password_confirm` | 是 | 再次輸入密碼，必須與 `password` 完全相同。 |

#### 成功回應

Status: `201 Created`

```json
{
  "user": {
    "id": 1,
    "username": "PlayerOne",
    "email": "player@example.com",
    "email_verified": false,
    "nickname": "Player",
    "total_score": 0,
    "win_rate": 0.0
  },
  "message": "Registration successful. Please verify your email."
}
```

#### 常見錯誤

| 狀況 | 回傳 code |
|---|---|
| 帳號已存在 | `username_exists` |
| 信箱已存在 | `email_exists` |
| 密碼與確認密碼不同 | `password_mismatch` |
| email 格式錯誤 | `bad_request` |
| 密碼少於 8 字元 | `bad_request` |

### 2. 驗證信箱

```http
POST /api/auth/verify-email/
```

#### 用途

使用註冊時收到的 6 位數驗證碼啟用帳號。

驗證成功後：

```text
email_verified = true
```

#### Request Body

```json
{
  "email": "player@example.com",
  "code": "123456"
}
```

#### 參數說明

| 參數 | 必填 | 說明 |
|---|---:|---|
| `email` | 是 | 要驗證的信箱。大小寫不敏感。 |
| `code` | 是 | 信箱收到的 6 位數驗證碼。有效時間為 15 分鐘。 |

#### 成功回應

Status: `200 OK`

```json
{
  "user": {
    "id": 1,
    "username": "PlayerOne",
    "email": "player@example.com",
    "email_verified": true,
    "nickname": "Player",
    "total_score": 0,
    "win_rate": 0.0
  },
  "message": "Email verified."
}
```

#### 常見錯誤

| 狀況 | HTTP status | 回傳 code |
|---|---:|---|
| 驗證碼錯誤或不存在 | `404` | `invalid_code` |
| 驗證碼過期 | `400` | `expired_code` |
| 缺少 email 或 code | `400` | `bad_request` |

### 3. 重寄信箱驗證碼

```http
POST /api/auth/resend-verification/
```

#### 用途

針對尚未完成信箱驗證的帳號，重新寄送 6 位數驗證碼。

#### Request Body

```json
{
  "email": "player@example.com"
}
```

#### 參數說明

| 參數 | 必填 | 說明 |
|---|---:|---|
| `email` | 是 | 尚未驗證的帳號信箱。 |

#### 成功回應

Status: `200 OK`

```json
{
  "message": "Verification code sent."
}
```

#### 常見錯誤

| 狀況 | HTTP status | 回傳 code |
|---|---:|---|
| 找不到尚未驗證的帳號 | `404` | `pending_user_not_found` |

### 4. 登入

```http
POST /api/auth/login/
```

#### 用途

使用 username 或 email 登入帳號。

登入成功後，Django 會建立 session cookie。之後呼叫需要登入狀態的 API 時，前端需要帶：

```js
credentials: 'include'
```

#### Request Body

```json
{
  "username": "PlayerOne",
  "password": "password123"
}
```

也可以用 email 登入：

```json
{
  "username": "player@example.com",
  "password": "password123"
}
```

#### 參數說明

| 參數 | 必填 | 說明 |
|---|---:|---|
| `username` | 是 | 可填 username 或 email。username 大小寫敏感；email 大小寫不敏感。 |
| `password` | 是 | 使用者密碼。 |

#### 成功回應

Status: `200 OK`

```json
{
  "user": {
    "id": 1,
    "username": "PlayerOne",
    "email": "player@example.com",
    "email_verified": true,
    "nickname": "Player",
    "total_score": 0,
    "win_rate": 0.0
  }
}
```

#### 常見錯誤

| 狀況 | HTTP status | 回傳 code |
|---|---:|---|
| 帳號或密碼錯誤 | `401` | `invalid_credentials` |
| 信箱尚未驗證 | `403` | `email_not_verified` |
| 缺少帳號或密碼 | `400` | `bad_request` |

### 5. 登出

```http
POST /api/auth/logout/
```

#### 用途

登出目前登入的使用者，清除 Django session。

#### Request Body

可以送空 JSON：

```json
{}
```

#### 成功回應

Status: `200 OK`

```json
{
  "message": "Logged out."
}
```

### 6. 取得目前登入使用者

```http
GET /api/auth/me/
```

#### 用途

確認目前瀏覽器 session 是否已登入，並取得目前使用者資料。

#### Request Body

此 API 不需要 body。

#### 成功回應

Status: `200 OK`

```json
{
  "user": {
    "id": 1,
    "username": "PlayerOne",
    "email": "player@example.com",
    "email_verified": true,
    "nickname": "Player",
    "total_score": 0,
    "win_rate": 0.0
  }
}
```

#### 常見錯誤

| 狀況 | HTTP status | 回傳 code |
|---|---:|---|
| 尚未登入 | `401` | `not_authenticated` |

### 7. 申請忘記密碼重設連結

```http
POST /api/auth/request-password-reset/
```

#### 用途

使用者忘記密碼時，輸入 email。若該 email 對應到已啟用帳號，系統會寄出一封重設密碼連結。

為了避免有人用此 API 查詢哪些 email 有註冊，無論 email 是否存在，成功回應都會使用同一段訊息。

#### Request Body

```json
{
  "email": "player@example.com"
}
```

#### 參數說明

| 參數 | 必填 | 說明 |
|---|---:|---|
| `email` | 是 | 要重設密碼的帳號信箱。只有已完成信箱驗證的帳號會收到重設連結。 |

#### 成功回應

Status: `200 OK`

```json
{
  "message": "If the email is registered, a password reset link has been sent."
}
```

#### 重設連結格式

後端會根據 `FRONTEND_BASE_URL` 產生連結，目前預設為：

```text
http://127.0.0.1:5173
```

實際信件中的連結格式：

```text
http://127.0.0.1:5173/?reset_email=player%40example.com&reset_token=<token>
```

前端會讀取：

| Query 參數 | 說明 |
|---|---|
| `reset_email` | 要重設密碼的 email。 |
| `reset_token` | 一次性重設密碼 token。 |

### 8. 重設密碼

```http
POST /api/auth/reset-password/
```

#### 用途

使用 email 中的 reset token 設定新密碼。

重設成功後，該 token 會從資料表刪除，因此同一個連結只能使用一次。

#### Request Body

```json
{
  "email": "player@example.com",
  "token": "reset-token-from-email",
  "new_password": "newpassword123",
  "new_password_confirm": "newpassword123"
}
```

#### 參數說明

| 參數 | 必填 | 說明 |
|---|---:|---|
| `email` | 是 | 要重設密碼的帳號信箱。 |
| `token` | 是 | 信件連結中的 `reset_token`。有效時間為 15 分鐘，且只能使用一次。 |
| `new_password` | 是 | 新密碼，至少 8 個字元。 |
| `new_password_confirm` | 是 | 再次輸入新密碼，必須與 `new_password` 完全相同。 |

#### 成功回應

Status: `200 OK`

```json
{
  "message": "Password reset successful. You can log in now."
}
```

#### 常見錯誤

| 狀況 | HTTP status | 回傳 code |
|---|---:|---|
| token 錯誤或已被使用 | `404` | `invalid_token` |
| token 過期 | `400` | `expired_token` |
| 新密碼與確認密碼不同 | `400` | `password_mismatch` |
| 新密碼少於 8 字元 | `400` | `bad_request` |

### 補充規則

#### Username

```text
username 大小寫敏感
```

例如：

```text
Ray
ray
```

會被視為不同帳號。

#### Email

```text
email 大小寫不敏感
```

例如：

```text
Player@Example.com
player@example.com
```

會被視為同一個 email。後端會轉成小寫處理。

#### 密碼

目前規則：

```text
至少 8 個字元
```

註冊與重設密碼都需要二次輸入確認。
