# Deployment Information

## Public URL
https://day14-agent-7egh.onrender.com

## Platform
Render (Blueprint `lab14`, region Singapore, plan free), deploy từ [`06-lab-complete/render.yaml`](06-lab-complete/render.yaml).

| Service | Loại | Vai trò |
|---|---|---|
| `day14-agent` | Web service (Docker, multi-stage `06-lab-complete/Dockerfile`) | FastAPI agent, health check `/health` |
| `day14-redis` | Key Value (Redis) | State dùng chung cho rate limiter và cost guard |

> Plan free ngủ sau 15 phút không có request; request đầu tiên sau đó mất ~30–50 giây để khởi động lại.

## Test Commands

```bash
URL=https://day14-agent-7egh.onrender.com
KEY=YOUR_KEY   # lấy ở Render → day14-agent → Environment → AGENT_API_KEY
```

### Health Check
```bash
curl $URL/health
# {"status":"ok"}            HTTP 200
```

### Readiness (Redis đã kết nối)
```bash
curl $URL/ready
# {"ready":true}             HTTP 200
```

### Authentication required
```bash
curl -X POST $URL/ask -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"Hello"}'
# {"detail":"Invalid or missing API key"}   HTTP 401

curl -X POST $URL/ask -H "X-API-Key: wrong" -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"Hello"}'
# {"detail":"Invalid or missing API key"}   HTTP 401
```

### API Test (with authentication)
```bash
curl -X POST $URL/ask \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Bạn là ai"}'
# HTTP 200
# {"question":"Bạn là ai","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"mock-llm"}
```

Kiểm tra qua Swagger UI (`/docs`) ngày 2026-11-25 15:25:47 GMT: [screenshots/ask-200-swagger.png](screenshots/ask-200-swagger.png).

### Rate limiting (10 req/phút)
```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "$i: %{http_code}\n" -X POST $URL/ask \
    -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    -d '{"user_id":"test","question":"test"}'
done
```

Output thật (2026-11-25):
```text
1: 200
2: 200
3: 200
4: 200
5: 200
6: 200
7: 200
8: 200
9: 200
10: 200
11: 429
12: 429
13: 429
14: 429
15: 429
```
→ Đúng 10 request/phút/API key; request thứ 11 trở đi bị chặn với HTTP 429. Bộ đếm nằm trong Redis (`day14-redis`) nên giới hạn vẫn đúng khi scale nhiều instance.

## Environment Variables Set
| Biến | Giá trị / nguồn |
|---|---|
| `PORT` | Render tự inject |
| `ENVIRONMENT` | `production` |
| `AGENT_API_KEY` | Render tự sinh (`generateValue: true`), không nằm trong repo |
| `REDIS_URL` | `fromService` → `connectionString` của `day14-redis` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `10` |

## Deploy log (rút gọn)
```text
==> Deploying...
==> Your service is live 🎉
==> Available at your primary URL https://day14-agent-7egh.onrender.com
INFO:     10.237.25.117:48698 - "GET /health HTTP/1.1" 200 OK
{"ts": 1795619708.3656905, "lvl": "INFO", "event": "http_request", "method": "GET", "path": "/health", "status": 200, "ms": 0.69}
```

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
- [POST /ask với API key → 200 (Swagger UI)](screenshots/ask-200-swagger.png)
