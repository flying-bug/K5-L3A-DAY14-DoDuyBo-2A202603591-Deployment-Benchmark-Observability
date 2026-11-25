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

## AI log

| Lúc | Hỏi AI gì | Nhận được gì | Mình tự kiểm tra thế nào |
|---|---|---|---|
| Part 1 | Nhờ Claude Code đọc `develop/app.py` và `production/app.py`, chạy hai bản và soạn câu trả lời Part 1 | Danh sách anti-pattern kèm số dòng, bảng so sánh, output curl thật, phát hiện uvicorn xoá handler của `basicConfig` | Tự chạy lại các lệnh curl ở trên và so với output; đối chiếu số dòng trong `develop/app.py` |
