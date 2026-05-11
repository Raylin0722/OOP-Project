# GitHub 使用流程說明

本專案建議每位成員都在自己的 branch 上進行編輯，不直接修改 `main`，以避免互相覆蓋內容，並方便統整每位成員的撰寫結果。

---

## 協作流程概念

每次要開始撰寫或修改內容時，請依照以下流程進行：

1. 先切回 `main`
2. 從遠端更新 `main` 的最新內容
3. 建立自己的 branch
4. 在自己的 branch 上新增或修改內容
5. 將修改加入暫存區並 commit
6. push 到自己的 branch
7. 到 GitHub 上發出 Pull Request，請求合併到 `main`

---

## 1. 切換到 main 分支

```bash
git checkout main
```

或新版寫法：

```bash
git switch main
```

---

## 2. 更新 main 的最新內容

```bash
git pull origin main
```

這一步的目的是確保你的本地 `main` 與 GitHub 上的 `main` 一致，避免你從舊版本開 branch。

---

## 3. 建立自己的 branch

請用有意義的 branch 名稱，例如：

- `feature-introduction`
- `feature-memberA`
- `update-report-part1`

建立並切換到自己的 branch：

```bash
git checkout -b 你的branch名稱
```

例如：

```bash
git checkout -b feature-memberA
```

或新版寫法：

```bash
git switch -c feature-memberA
```

---

## 4. 在自己的 branch 上進行撰寫與修改

接下來就可以開始新增、修改專案內容，例如：

- 撰寫 README
- 修改報告內容
- 補充程式碼
- 新增文件

可先用以下指令查看狀態：

```bash
git status
```

---

## 5. 將修改加入暫存區

加入所有修改過的檔案：

```bash
git add .
```

如果只想加入特定檔案，也可以寫成：

```bash
git add 檔名
```

例如：

```bash
git add README.md
```

---

## 6. 提交修改內容

```bash
git commit -m "簡短說明這次修改內容"
```

例如：

```bash
git commit -m "新增第一部分報告內容"
```

或：

```bash
git commit -m "更新 README 協作流程說明"
```

---

## 7. 將 branch 推送到 GitHub

```bash
git push -u origin 你的branch名稱
```

例如：

```bash
git push -u origin feature-memberA
```

第一次 push 使用 `-u`，之後若還在同一個 branch，可直接使用：

```bash
git push
```

---

## 8. 發出 Pull Request 請求合併

當你完成自己的修改後，請到 GitHub 專案頁面：

1. 進入該 repository
2. 找到你剛剛 push 上去的 branch
3. 點選 **Compare & pull request**
4. 確認要將你的 branch 合併到 `main`
5. 填寫標題與說明
6. 送出 Pull Request

這樣其他成員就可以檢查內容，確認後再合併到 `main`。

---

## 9. 若做到一半 main 更新

如果發現做到一半 main 有更新內容，則請遵循下面步驟

```bash
git checkout main # 也可以用 git switch main
git pull origin main
git checkout <Your branch> # 也可以用 git switch <Your branch>
git merge main
```


## 建議的完整操作流程範例

假設今天要撰寫自己的部分，branch 名稱為 `feature-memberA`，則流程如下：

```bash
git checkout main
git pull origin main
git checkout -b feature-memberA
git add .
git commit -m "新增 memberA 撰寫內容"
git push -u origin feature-memberA
```

接著再到 GitHub 上發出 Pull Request。

---

## 每次修改前的注意事項

- 不要直接在 `main` 上編輯後就 push
- 開始工作前，先更新 `main`
- 每個人盡量使用自己的 branch
- commit 訊息要簡單明確，方便查看紀錄
- 完成後再用 Pull Request 合併到 `main`

---

## 常用指令整理

### 更新 main
```bash
git checkout main
git pull origin main
```

### 建立並切換新 branch
```bash
git checkout -b branch名稱
```

### 查看狀態
```bash
git status
```

### 加入修改
```bash
git add .
```

### 提交修改
```bash
git commit -m "修改說明"
```

### 推送到自己的 branch
```bash
git push -u origin branch名稱
```

---

### Docker 啟動說明

本專案使用 `docker-compose.yml` 統一管理開發環境，目前包含以下服務：

- `redis`：提供即時通訊所需的 Redis 服務
- `backend`：Django + Channels 後端服務
- `frontend`：Vue 3 + Vite 前端開發環境

---

#### 1. 啟動 Docker 服務

請先確認已安裝：

- Docker
- Docker Compose

接著在**專案根目錄**下執行：

```bash
docker compose up --build
```

如果使用的是舊版指令，也可以改用：

```bash
docker-compose up --build
```

---

#### 2. 背景執行

若不想讓終端機持續占用，可使用：

```bash
docker compose up --build -d
```

---

#### 3. 關閉服務

停止並關閉所有容器：

```bash
docker compose down
```

若要連同 volume 一起移除，可使用：

```bash
docker compose down -v
```

---

#### 4. 服務對應埠號

啟動後可透過以下埠號存取服務：

- Frontend：`http://localhost:5173`
- Backend：`http://localhost:8000`
- Redis：`localhost:6379`

---

#### 5. 補充說明

- `frontend` 容器啟動時會自動執行 `npm install` 並啟動 Vite。
- `backend` 目前已設定 Redis 環境變數，供 Django / Channels 使用。
- **目前 `backend` 的啟動指令仍待後端功能完成後補上，日後完成撰寫時請記得打開對應的 `command` 設定，否則後端服務不會正常啟動。**
