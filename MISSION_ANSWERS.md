# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Đọc `01-localhost-vs-production/develop/app.py`, tìm được 9 vấn đề:

| # | Anti-pattern | Dòng code | Hậu quả |
|---|---|---|---|
| 1 | Hardcode secret | `OPENAI_API_KEY = "sk-hardcoded-..."` (dòng 17) | Push lên GitHub là lộ key; muốn đổi key phải sửa code và deploy lại |
| 2 | Hardcode credential DB | `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` (dòng 18) | Lộ mật khẩu DB; `localhost` không tồn tại trong container/cloud |
| 3 | Log ra secret | `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` (dòng 34) | Key nằm trong log, ai đọc log (log aggregator, đồng nghiệp) đều thấy |
| 4 | `print()` thay vì logging có cấu trúc | dòng 33, 38 | Không có level, timestamp, không parse được bằng Loki/Datadog; còn log nguyên câu hỏi và câu trả lời của user |
| 5 | Config cứng, không đọc env | `DEBUG = True`, `MAX_TOKENS = 500` (dòng 21–22) | Không đổi được giữa dev/staging/prod mà không sửa code; debug bật cả trên production |
| 6 | Không có health check | không có `/health`, `/ready` | Platform không biết app chết để restart, load balancer không biết khi nào route traffic |
| 7 | Bind `localhost` và port cứng | `host="localhost", port=8000` (dòng 51–52) | Trong container, `localhost` chỉ nhận kết nối từ bên trong nên không ai gọi được; Railway/Render inject `PORT` qua env nên app sai cổng |
| 8 | `reload=True` trên mọi môi trường | dòng 53 | Chạy thêm process theo dõi file, tốn tài nguyên, có thể tự restart giữa chừng trên production |
| 9 | Không xử lý shutdown | không có lifespan / SIGTERM handler | Khi platform tắt container, request đang chạy bị cắt ngang |

### Exercise 1.2: Chạy basic version

> Ghi chú: trên máy mình cổng 8000 đang bị một container Docker khác chiếm, nên chạy bản develop ở cổng 8010 bằng `python -m uvicorn app:app --host 127.0.0.1 --port 8010` (code không đổi).

```text
$ curl -i -X POST "http://127.0.0.1:8010/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -i -X POST http://127.0.0.1:8010/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://127.0.0.1:8010/health
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

Log phía server:

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
INFO:     127.0.0.1:63434 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Quan sát:** app chạy được và trả lời, nhưng chưa sẵn sàng cho production: secret bị in thẳng ra log, không có `/health` (404), `question` nhận qua query string nên gửi JSON bị 422, và app chỉ nghe trên `localhost` nên không chạy được trong container.

### Exercise 1.3: Comparison table

Chạy bản production ở cổng 8011: `PORT=8011 HOST=127.0.0.1 ENVIRONMENT=staging python app.py` (cấu hình qua biến môi trường, không tạo file `.env`).

```text
$ curl -i http://127.0.0.1:8011/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"staging","timestamp":"2026-11-25T07:56:04.366060+00:00"}

$ curl -i http://127.0.0.1:8011/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://127.0.0.1:8011/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}

$ curl -i -X POST http://127.0.0.1:8011/ask -H "Content-Type: application/json" -d '{}'
HTTP/1.1 422 Unprocessable Entity
{"detail":"question field is required"}
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`, key, DB URL) | Đọc từ env trong `config.py` (`Settings`), có `validate()` fail fast khi thiếu `AGENT_API_KEY` ở production | Cùng một image chạy được ở dev/staging/prod chỉ bằng cách đổi env; secret không nằm trong code và lịch sử git |
| Secrets | `OPENAI_API_KEY` viết thẳng trong code và in ra log | Lấy từ env, không bao giờ log; chỉ log độ dài câu hỏi/câu trả lời | Lộ key trên GitHub hay trong log là bị dùng trộm, tốn tiền; phải revoke key |
| Health check | Không có (`/health` → 404) | `/health` (liveness, có uptime, version) và `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform dùng `/health` để restart container chết; load balancer dùng `/ready` để không route traffic vào instance đang khởi động hoặc đang tắt |
| Logging | `print()` không level, không timestamp, log cả secret | `logging` với format JSON, log sự kiện (`agent_request`, `agent_response`) không chứa secret | Log aggregator parse/lọc/alert được theo field; không rò rỉ dữ liệu nhạy cảm |
| Shutdown | Đột ngột, không có hook | `lifespan` đặt `is_ready = False` rồi dọn dẹp; có handler `SIGTERM` | Khi deploy bản mới hoặc scale down, request đang chạy được hoàn thành thay vì bị cắt |
| Host / Port | `localhost:8000` cố định | `HOST` (mặc định `0.0.0.0`) và `PORT` từ env | Container cần nghe trên `0.0.0.0`; Railway/Render inject `PORT` động |
| Reload | `reload=True` luôn bật | `reload=settings.debug` (chỉ khi `DEBUG=true`) | Tránh process thừa và tự restart trên production |
| Input | `question` qua query string, không kiểm tra | JSON body, trả 422 với thông báo rõ khi thiếu `question` | API rõ ràng, lỗi dễ hiểu cho client |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép mới gọi được từ trình duyệt |

**Quan sát thêm:** khi chạy bản production bằng `python app.py`, các dòng log JSON của app (`startup`, `agent_request`…) **không xuất hiện** trong output, chỉ có log của uvicorn. Nguyên nhân: `uvicorn.run()` gọi `logging.config.dictConfig(...)`, và hàm này xoá các handler mà `logging.basicConfig` đã gắn vào root logger từ lúc import. Muốn log JSON hiện ra thì phải cấu hình logging sau khi uvicorn khởi động (ví dụ trong `lifespan`) hoặc truyền `log_config` riêng cho uvicorn. Cần lưu ý điều này khi làm tiêu chí "Structured logging" ở Part 6.

### Checkpoint 1

- **Vì sao hardcode secret nguy hiểm:** code được push lên Git, mà lịch sử Git giữ secret mãi mãi kể cả sau khi xoá file; ai clone repo cũng có key. Muốn đổi key phải sửa code và deploy lại. Bản develop còn in key ra log nên lộ thêm qua log.
- **Cách dùng biến môi trường:** đọc bằng `os.getenv("PORT", "8000")` tập trung trong một `Settings`; giá trị thật đặt trên platform (Railway/Render variables) hoặc file `.env` không commit; chỉ commit `.env.example` không có giá trị thật.
- **Vai trò của health check:** `/health` (liveness) trả lời "process còn sống không" để platform restart khi chết; `/ready` (readiness) trả lời "có nhận request được chưa" để load balancer chỉ gửi traffic khi app đã khởi động xong và dependency (DB, Redis) sẵn sàng.
- **Graceful shutdown:** khi nhận SIGTERM, app ngừng nhận request mới (`/ready` → 503), chờ request đang chạy xong, đóng kết nối, rồi mới thoát với exit code 0.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

Đọc `02-docker/develop/Dockerfile`:

1. **Base image:** `python:3.11`, bản Python đầy đủ (Debian kèm gcc, header, nhiều tool build), nặng gần 1 GB. Đây là lý do image develop to (xem 2.3).
2. **Working directory:** `WORKDIR /app`. Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong `/app`. Kiểm tra bằng `docker exec ... ls /app` thấy `app.py  requirements.txt  utils/`.
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo từng layer, layer nào có input đổi thì layer đó và mọi layer sau phải build lại. `requirements.txt` ít khi đổi, còn code đổi liên tục. Copy requirements rồi `pip install` trước thì khi chỉ sửa `app.py`, Docker dùng lại layer `pip install` (53.3 MB, xem `docker history my-agent:develop`) và chỉ build lại layer `COPY app.py`. Nếu `COPY . .` trước thì mỗi lần sửa code là cài lại toàn bộ dependencies.
4. **CMD vs ENTRYPOINT:**
   - `CMD` là lệnh *mặc định*: `docker run my-agent:develop bash` sẽ thay `CMD` bằng `bash`.
   - `ENTRYPOINT` là executable *cố định* của container: tham số của `docker run` được nối vào sau nó, muốn đổi phải dùng `--entrypoint`.
   - Hay dùng kết hợp: `ENTRYPOINT ["uvicorn"]` + `CMD ["main:app", "--port", "8000"]` (CMD làm tham số mặc định).
   - Cả hai nên viết dạng exec (`["python", "app.py"]`) để process app là PID 1 và nhận được SIGTERM khi `docker stop`. Dạng shell (`CMD python app.py`) chạy qua `/bin/sh -c`, signal có thể không tới app.

### Exercise 2.2: Build và run

Build từ gốc repo (Dockerfile `COPY` theo đường dẫn tính từ gốc). Cổng 8000 trên máy đang bận nên map ra cổng 8020:

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --name d14-dev -p 8020:8000 my-agent:develop

$ curl -i -X POST "http://localhost:8020/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8020/health
{"status":"ok","uptime_seconds":4.0,"container":true}

$ docker exec d14-dev sh -c 'whoami; python --version'
root
Python 3.11.18
```

Quan sát: container chạy với user **root** (không có `USER`), điều này không an toàn cho production. Bản develop nhận `question` qua query string.

### Exercise 2.3: Multi-stage build và so sánh kích thước

```text
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
$ docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   a9784448e2df        240MB         57.4MB
my-agent:develop    b081059f5659       1.67GB          426MB

$ docker image inspect -f '{{.RepoTags}} {{.Size}}' my-agent:develop my-agent:advanced
[my-agent:develop] 1667788184
[my-agent:advanced] 239815307
```

- Develop: **1667.8 MB** (1.67 GB)
- Production: **239.8 MB**
- Chênh lệch: production nhỏ hơn **85.6%** (239815307 / 1667788184 = 14.4%), tức nhỏ hơn khoảng 7 lần.

**Stage 1 (`builder`):** từ `python:3.11-slim`, cài `gcc`, `libpq-dev` để build package có phần C, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Image này chỉ dùng để build, không deploy.

**Stage 2 (`runtime`):** bắt đầu lại từ `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local` (các package đã cài) cùng `main.py`, `utils/`. Tạo user `appuser` và chạy non-root, đặt `HEALTHCHECK` gọi `/health`, chạy `uvicorn main:app --workers 2`.

**Vì sao nhỏ hơn:**
1. Base `slim` thay vì bản đầy đủ: bỏ gcc, header, tài liệu, nên riêng base đã nhỏ hơn khoảng 850 MB.
2. Công cụ build (`gcc`, `libpq-dev`, apt cache) chỉ nằm ở stage 1, không đi vào image cuối.
3. `pip install --no-cache-dir` nên không có cache pip trong image.

Image Part 6 (`06-lab-complete/Dockerfile`, cũng multi-stage): **297 MB** theo `check_production_ready.py`.

### Exercise 2.4: Docker Compose stack

Chạy `touch .env.local` trong `02-docker/production/` rồi `docker compose -p k5-day14-docker up -d --build`:

```text
SERVICE  STATUS                  PORTS
agent    Up 7 seconds (healthy)  8000/tcp
nginx    Up 7 seconds            0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant   Up 18 seconds (healthy) 6333-6334/tcp
redis    Up 17 seconds (healthy) 6379/tcp
```

Architecture:

```text
                    host :80 / :443
                         │
              ┌──────────▼──────────┐
 Client ────► │ nginx (nginx:alpine)│  reverse proxy, rate limit 10 r/s (burst 20),
              └──────────┬──────────┘  security headers, 429 JSON
                         │ http://agent:8000  (upstream agent_backend)
              ┌──────────▼──────────┐
              │ agent (FastAPI,     │  build từ 02-docker/production/Dockerfile
              │ target: runtime)    │  không publish port ra host
              └─────┬──────────┬────┘
   redis://redis:6379/0        http://qdrant:6333
              ┌─────▼─────┐ ┌──▼──────────────┐
              │ redis:7   │ │ qdrant v1.9.0   │
              │ session,  │ │ vector DB (RAG) │
              │ rate limit│ │                 │
              └───────────┘ └─────────────────┘
     tất cả trong network bridge "internal"; volume redis_data, qdrant_data
```

- **Services được start:** 4 service: `redis` và `qdrant` lên trước. `agent` có `depends_on ... condition: service_healthy` nên chờ hai service đó healthy mới start. `nginx` start sau `agent`.
- **Giao tiếp:** cùng network `internal`, gọi nhau bằng **tên service** qua DNS nội bộ của Docker (`agent:8000`, `redis:6379`, `qdrant:6333`). Chỉ `nginx` publish cổng ra host, còn agent, Redis, Qdrant không truy cập được từ ngoài.

Test qua Nginx:

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":5.9,"version":"2.0.0","timestamp":"2026-11-25T10:30:23.733071"}

$ curl -i http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Dọn: `docker compose -p k5-day14-docker down -v`.

### Checkpoint 2

- Debug container: `docker logs <container>` xem stdout/stderr, `docker exec -it <container> sh` vào trong container, `docker inspect` xem state/exit code, `docker history <image>` xem layer nào nặng.

---

## Part 3: Cloud Deployment

> Lớp K5 deploy chính agent Part 6 (`06-lab-complete/`) ở CP6. Nền tảng chính: **Render**.

### Exercise 3.2: Render deployment

- URL: https://day14-agent-7egh.onrender.com (chi tiết và kết quả test trong `DEPLOYMENT.md`)
- Cách deploy: Render Dashboard → New → Blueprint → chọn repo, Blueprint Path `06-lab-complete/render.yaml`. Blueprint tạo hai service: web `day14-agent` (Docker) và Key Value `day14-redis` (Redis); `REDIS_URL` của agent lấy từ `connectionString` của Key Value; `AGENT_API_KEY` do Render tự sinh (`generateValue: true`).

### So sánh `railway.toml` và `render.yaml`

| Điểm | `railway.toml` | `render.yaml` | Vì sao khác |
|---|---|---|---|
| Phạm vi | Cấu hình **một** service: cách build và deploy | **Blueprint** mô tả cả hạ tầng: web service + Key Value (Redis) + biến môi trường | Railway quản lý project/database trên dashboard hoặc CLI; Render muốn khai báo toàn bộ hạ tầng dạng code |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"` (tính từ thư mục chạy `railway up`, tức `06-lab-complete/`) | `runtime: docker`, `dockerContext` / `dockerfilePath` tính từ **gốc repo** (`./06-lab-complete/...`) | Railway upload thư mục hiện tại; Render clone cả repo từ GitHub |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 10` | `healthCheckPath: /health` | Cùng ý nghĩa, khác tên khoá |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Render tự restart, không cần khai báo | |
| Biến môi trường / secret | Không ghi trong file; đặt bằng `railway variables set AGENT_API_KEY=...` | Khai báo trong file: giá trị thường ghi thẳng (`RATE_LIMIT_PER_MINUTE: "10"`), secret dùng `generateValue: true` hoặc `sync: false`, Redis dùng `fromService` | Render cần biết danh sách biến để tạo service từ Blueprint, nhưng không được ghi giá trị secret |
| Redis | Thêm plugin Redis trên dashboard, Railway inject `REDIS_URL` | Khai báo service `type: keyvalue` ngay trong file | |
| Port | Railway inject `PORT`; Dockerfile chạy `--port ${PORT:-8000}` | Render cũng inject `PORT` (mặc định 10000) | Vì thế CMD không được cố định port |

### Exercise 3.3: Cloud Run CI/CD (đọc `cloudbuild.yaml` và `service.yaml`)

Pipeline Cloud Build chạy 4 bước nối tiếp nhau (`waitFor`), bước nào lỗi thì dừng:

1. **test**: trong container `python:3.11-slim`, cài `requirements.txt` + `pytest` rồi chạy `pytest tests/`. Test fail thì không build.
2. **build**: `docker build` với hai tag `ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from` image `latest` để tận dụng layer cache.
3. **push**: đẩy cả hai tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **deploy**: `gcloud run deploy` image đúng `$COMMIT_SHA` (truy vết và rollback được) lên `asia-southeast1`: min 1 instance (tránh cold start), max 10, 512 Mi / 1 CPU, timeout 60 s, secret lấy từ **Secret Manager** (`--set-secrets`), không ghi trong code.

`service.yaml` là cấu hình tương đương dạng khai báo (Knative): autoscale 1–10 instance, `containerConcurrency: 80`, `livenessProbe` gọi `/health` mỗi 30 s, `startupProbe` gọi `/ready` (thử tối đa 10 lần × 3 s), `OPENAI_API_KEY` và `AGENT_API_KEY` lấy bằng `secretKeyRef`. Lưu ý: repo không có thư mục `tests/`, nên bước test sẽ fail nếu chạy nguyên trạng.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Key được kiểm tra ở đâu:** hàm `verify_api_key` (dòng 39) đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)`, so với `API_KEY = os.getenv("AGENT_API_KEY", ...)`. Endpoint `/ask` gắn nó bằng `Depends(verify_api_key)`; `/` và `/health` để public.
- **Sai key thì sao:** thiếu header trả **401** `Missing API key`; có header nhưng sai trả **403** `Invalid API key`. Request bị chặn trước khi gọi LLM.
- **Rotate key:** key đọc từ env nên chỉ cần đổi `AGENT_API_KEY` trên platform rồi restart/redeploy, không sửa code. Muốn không gián đoạn client thì cho app nhận **danh sách** key (cũ + mới) trong một khoảng chuyển tiếp, báo client đổi sang key mới, rồi xoá key cũ. Lưu ý bản develop còn `print(f"API Key: {API_KEY}")` lúc khởi động (dòng 91), là lộ key qua log.

Chạy bằng `AGENT_API_KEY=secret-key-123` (cổng 8030 vì 8000 bận):

```text
$ curl -i -X POST http://127.0.0.1:8030/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://127.0.0.1:8030/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://127.0.0.1:8030/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

**JWT flow (`auth.py`):**

1. Client gọi `POST /auth/token` với username/password; `authenticate_user` so với `DEMO_USERS` (sai thì 401).
2. `create_token` ký JWT **HS256** bằng `JWT_SECRET` (từ env), payload gồm `sub` (username), `role`, `iat`, `exp` = 60 phút.
3. Client gửi `Authorization: Bearer <token>` ở mỗi request.
4. `verify_token` giải mã, kiểm chữ ký và hạn: hết hạn trả 401 `Token expired`, chữ ký sai trả 403 `Invalid token`. Hợp lệ thì trả `{username, role}` cho endpoint mà **không cần tra DB**, vì thông tin nằm sẵn trong token đã ký (stateless).

```text
$ curl -i -X POST http://127.0.0.1:8031/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"wrong"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -X POST http://127.0.0.1:8031/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token":"eyJ***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."}

$ curl -i -X POST http://127.0.0.1:8031/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://127.0.0.1:8031/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i -X POST http://127.0.0.1:8031/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Thuật toán:** **sliding window** (dạng *sliding window log*): mỗi user có một `deque` timestamp; mỗi request xoá timestamp cũ hơn 60 s rồi đếm. Đủ `max_requests` thì trả 429 kèm `Retry-After` và `X-RateLimit-*`. Docstring gọi là "Sliding Window Counter" nhưng code thực ra lưu từng timestamp, tức sliding window log.
- **Giới hạn:** user thường (`student`) **10 request/phút**; admin (`teacher`) 100 request/phút.
- **Bypass cho admin:** `app.py` chọn `rate_limiter_admin if role == "admin" else rate_limiter_user`, nên admin không bị bỏ qua hẳn mà dùng một bậc giới hạn cao hơn (100/phút). Role nằm trong JWT đã ký nên client không tự nâng quyền được.

Vòng lặp 20 request với token `student`:

```text
req  1: HTTP/1.1 200 OK {"question":"Test 1",...,"usage":{"requests_remaining":8,...}}
req  2: HTTP/1.1 200 OK {"question":"Test 2",...,"usage":{"requests_remaining":7,...}}
...
req  9: HTTP/1.1 200 OK {"question":"Test 9",...,"usage":{"requests_remaining":0,...}}
req 10: HTTP/1.1 429 Too Many Requests retry-after: 58 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
req 11: HTTP/1.1 429 Too Many Requests retry-after: 58 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
...
req 20: HTTP/1.1 429 Too Many Requests retry-after: 58 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}

$ curl http://127.0.0.1:8031/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":288,"cost_usd":0.000179,"budget_usd":1.0,"budget_remaining_usd":0.999821,"budget_used_pct":0.0}
```

**Quan sát:** 429 xuất hiện từ request thứ 10 của vòng lặp, vì request "Explain JWT" ở 4.2 đã tính là request đầu tiên (tổng 10 request được chấp nhận trong 60 s, khớp `/me/usage` `requests: 10`). Limiter này lưu trong RAM, nên khi chạy nhiều instance mỗi instance đếm riêng và limit thực tế bị nhân lên; Part 6 chuyển sang Redis (sorted set) để tránh chuyện đó. Phát hiện thêm: field `usage.budget_remaining_usd` trong response `/ask` thực ra trả **số tiền đã dùng** (`usage.total_cost_usd`), không phải số còn lại.

### Exercise 4.4: Cost guard

**Bản mẫu `04-api-gateway/production/cost_guard.py`:** đếm token input/output mỗi user mỗi ngày trong RAM, quy ra USD theo giá gpt-4o-mini ($0.15 / 1M input, $0.60 / 1M output). `check_budget` gọi **trước** LLM: vượt $1/ngày/user thì **402**, tổng toàn hệ thống vượt $10/ngày thì **503**, dùng tới 80% thì log cảnh báo. `record_usage` gọi **sau** LLM để cộng chi phí thật.

**Cách mình làm ở Part 6 (`06-lab-complete/app/cost_guard.py`), state trong Redis:**

```python
def _cost_key() -> str:
    return f"cost:{datetime.now(timezone.utc):%Y-%m-%d}"   # mỗi ngày UTC một key

def check_budget() -> None:                    # gọi TRƯỚC khi gọi LLM
    spent = float(r.get(_cost_key()) or 0.0)
    if spent >= settings.daily_budget_usd:     # DAILY_BUDGET_USD từ env
        raise HTTPException(status_code=402, detail="Daily budget exceeded")

def record_cost(input_tokens, output_tokens):  # gọi SAU khi gọi LLM
    cost = input_tokens/1000*0.00015 + output_tokens/1000*0.0006
    pipe = r.pipeline()
    pipe.incrbyfloat(_cost_key(), cost)        # cộng dồn atomic, mọi instance dùng chung
    pipe.expire(_cost_key(), 2*24*3600)        # key cũ tự hết hạn → budget tự reset
    pipe.execute()
```

- **Vì sao Redis:** nhiều instance/worker phải thấy chung một tổng chi phí; `INCRBYFLOAT` là atomic nên không mất cập nhật khi nhiều request chạy song song; restart app không làm mất số đã tiêu.
- **Reset theo kỳ:** key có ngày trong tên nên sang ngày mới dùng key mới; TTL dọn key cũ. Theo đề bài ($10/tháng/user) thì chỉ cần đổi key thành `budget:{user_id}:{YYYY-MM}` với TTL 32 ngày, như lời giải trong `CODE_LAB.md`.
- **Hạn chế đã biết:** "check rồi mới cộng" không atomic, nên vài request song song sát ngưỡng có thể vượt budget thêm đúng chi phí của chúng (vài phần nghìn USD). Muốn chặn tuyệt đối thì gộp check + cộng vào một Lua script.
- **Kiểm chứng:** `check_production_ready.py` chạy agent với `DAILY_BUDGET_USD=0.000001` và nhận **402** (tiêu chí 8 ✅).

**Vì sao cần cả rate limit và cost guard:** rate limit bảo vệ **tốc độ** (chống spam/DoS, chia đều tài nguyên), còn cost guard bảo vệ **tiền**. Một client gửi đúng 10 request/phút nhưng mỗi request là prompt rất dài vẫn có thể đốt ngân sách, nên cần chặn theo tổng chi phí chứ không chỉ theo số request.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

Bản develop đã có sẵn hai endpoint:

- `GET /health` (**liveness**): process còn sống không. Trả 200 kèm uptime, version, % RAM (psutil). Không kiểm dependency, vì nếu Redis chết mà `/health` báo lỗi thì platform sẽ restart container liên tục mà không giải quyết được gì.
- `GET /ready` (**readiness**): đã sẵn sàng nhận traffic chưa. Trả 503 khi `_is_ready = False` (đang khởi động hoặc đang shutdown); ở bản production và Part 6 còn trả 503 khi không ping được Redis. Load balancer dựa vào đây để ngừng gửi traffic tới instance đó (không restart).

Chạy trong container `python:3.11-slim` (mount thư mục `develop/`, cổng 8040):

```text
$ curl -i http://localhost:8040/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":112.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T10:34:20.107045+00:00","checks":{"memory":{"status":"ok","used_percent":14.2}}}

$ curl -i http://localhost:8040/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

(`in_flight_requests: 1` chính là request `/ready` đang được xử lý, do middleware đếm.)

### Exercise 5.2: Graceful shutdown

Code: middleware đếm `_in_flight_requests`; `lifespan` khi shutdown đặt `_is_ready = False` rồi chờ tối đa 30 s cho tới khi `_in_flight_requests == 0`; `uvicorn.run(..., timeout_graceful_shutdown=30)`; có thêm `signal.signal(SIGTERM, handle_sigterm)` để log.

Python trên Windows không gửi được SIGTERM, nên mình test trong container: gửi một request `/ask` (mock LLM chờ 3 s), 0.5 s sau chạy `docker stop` (gửi SIGTERM):

```text
request result: {"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."} [HTTP 200, 3.044653s]
docker stop took 2.91s, exit code 0

INFO:     172.17.0.1:34324 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
2026-11-25 10:34:23,387 INFO 🔄 Graceful shutdown initiated...
2026-11-25 10:34:23,387 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
2026-11-25 10:34:23,388 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết quả:** request đang chạy **vẫn hoàn thành với 200**, container thoát **exit code 0** sau 2.9 s (trước hạn 30 s của `docker stop -t 30`, không bị SIGKILL/137).

**Quan sát:** dòng `Received signal 15` của handler tự viết lại in **sau cùng**. Lý do là khi server chạy, uvicorn tạm thay signal handler bằng handler của nó (ngừng nhận kết nối mới, chờ request đang chạy, gọi lifespan shutdown), xong mới gọi lại handler cũ. Vì vậy phần graceful thật sự là do uvicorn + `lifespan` + `timeout_graceful_shutdown`, còn `handle_sigterm` chỉ để log. Ngoài ra, `ask_agent` là `async def` nhưng gọi `time.sleep` (blocking) nên chặn cả event loop trong 3 s; code thật nên dùng `def` (chạy trong threadpool) hoặc `await asyncio.sleep`.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

- Session và history lưu trong Redis: `save_session` dùng `SETEX session:{id}` với TTL 3600 s, `load_session` đọc lại, `append_to_history` thêm message vào session. Không có dict toàn cục nào giữ state khi có Redis (chỉ fallback `_memory_store` nếu không kết nối được Redis, và lúc đó `/health` báo `storage: in-memory`).
- **Vì sao:** khi scale ra N instance, mỗi instance có RAM riêng và load balancer gửi request lần lượt cho các instance. State trong RAM thì request thứ 2 của cùng user rơi vào instance khác sẽ không thấy history, và instance bị restart/scale down là mất state. Đưa state ra Redis thì instance nào cũng phục vụ được bất kỳ request nào, nên scale và thay instance thoải mái.

### Exercise 5.4: Load balancing

```text
$ cd 05-scaling-reliability/production && touch .env.local
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
k5-day14-scaling-agent-1   Up 9 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 8 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 8 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 8 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 19 seconds (healthy)  6379/tcp

$ for i in {1..10}; do curl -s http://localhost:8080/chat -X POST -H "Content-Type: application/json" -d '{"question": "Request '$i'"}'; done
req 1  instance-e679db redis
req 2  instance-a5c360 redis
req 3  instance-6fda49 redis
req 4  instance-e679db redis
req 5  instance-a5c360 redis
req 6  instance-6fda49 redis
req 7  instance-e679db redis
req 8  instance-a5c360 redis
req 9  instance-6fda49 redis
req 10 instance-e679db redis
```

- 3 instance agent được start; Nginx chia request **round-robin** (e679db → a5c360 → 6fda49 → lặp lại). `upstream agent_cluster { server agent:8000; }` cùng `resolver 127.0.0.11` dùng DNS của Docker, và tên `agent` trả về IP của cả 3 container.
- Khi một instance chết: `proxy_next_upstream error timeout http_503` + `proxy_next_upstream_tries 3` làm Nginx thử lại request ở instance khác, client không thấy lỗi.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: 511febd9-9dda-4d75-b548-3786b59c9928

Request 1: [instance-a5c360]  Q: What is Docker?
Request 2: [instance-6fda49]  Q: Why do we need containers?
Request 3: [instance-e679db]  Q: What is Kubernetes?
Request 4: [instance-a5c360]  Q: How does load balancing work?
Request 5: [instance-6fda49]  Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-6fda49', 'instance-a5c360', 'instance-e679db'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu trong **cùng một session** được 3 instance khác nhau trả lời, nhưng history đọc lại vẫn đủ **10 message** (5 user + 5 assistant) đúng thứ tự. Mỗi instance đọc/ghi `session:{id}` trong Redis dùng chung chứ không giữ trong RAM của mình. Nếu state nằm trong RAM, history sẽ bị chia nhỏ theo instance và mỗi lần đọc chỉ thấy phần do instance đó xử lý. Script không tự tắt instance nào (theo ghi chú K5). Dọn: `docker compose -p k5-day14-scaling down`.

### Checkpoint 5

- **Liveness vs readiness:** liveness sai thì platform **restart** container; readiness sai thì load balancer **ngừng gửi traffic** nhưng không restart (ví dụ đang khởi động, đang shutdown, mất Redis tạm thời).
- **State trong RAM hỏng khi scale:** mỗi instance có bộ nhớ riêng, request của một user rải qua nhiều instance, nên state bị phân mảnh và mất khi instance restart. Rate limiter trong RAM còn cho phép vượt limit N lần.

---

## Part 6: Final Project — `check_production_ready.py`

Chạy trong WSL Ubuntu (`os.name == "posix"`), Docker Desktop bật WSL integration, trong `06-lab-complete/`:

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

---

## Part 7: Benchmark & Observability

Báo cáo đầy đủ trong [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md), kèm `develop/reports/*.json`, `production/benchmark-results/scale_{1,3}_stats.csv` và 4 ảnh trong `screenshots/`. Tóm tắt:

- **7.1:** thêm Histogram `agent_question_length_chars` vào `develop/app.py` (không dùng label độ dài vì cardinality). Label `route` dùng template `route.path`, nên bot quét `/wp-admin`, `/.env`, ... đều gom vào `unmatched`. Dùng URL thật thì mỗi URL lạ thành một time series mới, Prometheus phình RAM.
- **7.2:** v2 đạt SLO p95 < 500 ms ở c=1 và c=10. Ở c=50 p95 = 545.9 ms, ở c=100 p95 = 4005.7 ms (quá tải, RPS còn giảm). `MOCK_SLOW_RATE` 0 → 0.03: avg +19 %, p99 ×3.3.
- **7.3:** v1 4.35 %, v2 91.3 %, v2 sau khi thêm KB HPA và JWT đạt **100 % (23/23), 0 regression**. CI: [`.github/workflows/eval.yml`](.github/workflows/eval.yml); `run_eval.py` exit 1 thì chặn merge.
- **7.4–7.6:** stack Prometheus/Grafana/Jaeger. Phải sửa `production/Dockerfile` (`PYTHONUSERBASE`) vì agent crash `No module named 'uvicorn'`. Alert firing: `AgentHighErrorRate` 86 s, `AgentHighLatencyP95` 153 s, `LLMCostBurnRateHigh` 148 s, `AgentInstanceDown` 42 s. Trace chậm `2b24cc29…`: span LLM chiếm 94.6 %.
- **Scale 1 → 3:** RPS không đổi (Locust closed-loop), p95 300 → 230 ms, p99 giữ 1700 ms vì nút thắt là LLM.

---

## AI log

| Lúc | Hỏi AI gì | Nhận được gì | Mình tự kiểm tra thế nào |
|---|---|---|---|
| Part 1 | Nhờ Claude Code đọc `develop/app.py` và `production/app.py`, chạy hai bản và soạn câu trả lời Part 1 | Danh sách anti-pattern kèm số dòng, bảng so sánh, output curl thật, phát hiện uvicorn xoá handler của `basicConfig` | Tự chạy lại các lệnh curl ở trên và so với output; đối chiếu số dòng trong `develop/app.py` |
| Part 2 | Nhờ Claude Code build hai image, đo kích thước, chạy stack Compose và soạn câu trả lời | Số đo `docker images` / `docker image inspect`, `docker history`, sơ đồ stack, output curl qua Nginx | Chạy lại `docker images my-agent`, so số MB; tự tính lại % chênh lệch |
| Part 3 | Nhờ Claude Code so sánh `railway.toml` / `render.yaml`, tóm tắt pipeline Cloud Run, sửa `render.yaml` để khai báo Redis | Bảng so sánh, mô tả 4 bước Cloud Build, phát hiện thiếu thư mục `tests/` | Đọc lại hai file cấu hình; deploy Render bằng Blueprint để kiểm tra |
| Part 4 | Nhờ Claude Code chạy bản develop/production, vòng lặp rate limit, giải thích JWT và cost guard | Output 401/403/200/429 thật, phát hiện field `budget_remaining_usd` trả sai giá trị, đề xuất cost key theo ngày có TTL | Tự chạy lại vòng lặp curl, thấy 429 ở request thứ 10; đọc `auth.py`, `rate_limiter.py` |
| Part 5 | Nhờ Claude Code test health/ready, graceful shutdown trong container, stack 3 instance và `test_stateless.py` | Output thật, giải thích thứ tự log signal của uvicorn, phân phối round-robin | Chạy lại `docker compose ... --scale agent=3` và `test_stateless.py`, xem `served_by` |
| Part 6 | Nhờ Claude Code hoàn thiện TODO, chạy `check_production_ready.py` trong WSL | `PASS 12/12` | Tự chạy lại script trong WSL Ubuntu |
| Part 7 | Nhờ Claude Code chạy load test/eval, sửa KB, dựng stack observability, chạy Locust scale 1/3, làm thí nghiệm alert, chụp Grafana/Jaeger/Prometheus và soạn `BENCHMARK_REPORT.md` | JSON/CSV report, 4 ảnh, thời gian firing của 4 alert; phát hiện lỗi Dockerfile và việc `docker compose run` tự đổi số replica | Đối chiếu từng số trong report với file JSON/CSV; xem lại ảnh; tự chạy `run_eval.py --min-accuracy 1.0` thấy PASS |
