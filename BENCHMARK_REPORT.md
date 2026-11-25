# Benchmark & Observability Report — Day 14

**Họ tên:** Đỗ Duy Bộ — 2A202603591
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 Pro, Python 3.12 (venv) cho Bước 1; Docker Desktop 29.8 (16 CPU / 8 GB cấp cho Docker) cho Bước 2. Mỗi container agent giới hạn `cpus: 0.5`, `memory: 256M` theo `docker-compose.yml`.

Bằng chứng:

- Load test và eval: [`reports/`](reports/) (bản gốc ghi ra ở `06-lab-complete/benchmark-observability/develop/reports/`)
- Locust CSV: [`benchmark-results/`](benchmark-results/) (bản gốc ở `06-lab-complete/benchmark-observability/production/benchmark-results/`)
- Ảnh: [`screenshots/`](screenshots/)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | LLM nhỏ trả lời mất ~150–200 ms. 500 ms gấp ~2.5 lần mức đó, đủ chỗ cho retrieval và tải cao vừa phải. Người dùng chat vẫn thấy "tức thì" dưới 0.5 s. Đây cũng là ngưỡng mặc định của `load_test.py`. Alert đặt lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn. |
| Error rate `/ask` | < 2 % | Mock LLM tự có ~1 % lỗi upstream. 2 % chừa error budget gấp đôi mức nền. Alert đặt ở 5 % trong 1 phút để chỉ báo khi lỗi tăng rõ rệt. |
| Accuracy trên golden dataset | ≥ 85 % (CI), 100 % cho bản release | 85 % là ngưỡng chặn merge trong CI ([`.github/workflows/eval.yml`](.github/workflows/eval.yml)). Bản release phải đạt 23/23 và không regression so với bản trước. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.96 | 201.6 | 233.8 | 1705.9 | 1.67 % | ✅ PASS |
| 10 | 40.79 | 190.0 | 235.9 | 1677.9 | 1.00 % | ✅ PASS |
| 50 | 95.57 | 205.0 | 545.9 | 1725.6 | 0.33 % | ❌ FAIL (p95) |
| 100 | 46.03 | 681.0 | 4005.7 | 4331.8 | 0.67 % | ❌ FAIL (p95) |

**Nhận xét:** RPS chỉ tăng gần tuyến tính ở đoạn đầu: c=1 → c=10 tăng ~10 lần (3.96 → 40.79). Ở đoạn này agent chủ yếu *chờ* LLM (I/O, `asyncio.sleep`), nên một event loop xử lý song song được nhiều request.

- **c=50:** RPS chỉ còn tăng ~2.3 lần (lên 95.57) và p95 bắt đầu vượt SLO (545.9 ms). Agent chạy 1 process, 1 event loop. Phần CPU của mỗi request (parse JSON, Pydantic, Prometheus, ghi log) bắt đầu xếp hàng, và client `load_test.py` chạy cùng máy cũng tranh CPU.
- **c=100:** RPS còn *giảm* (46.03) trong khi p50 lên 681 ms và p95 lên 4 s. Hệ thống đã quá tải: thêm concurrency chỉ làm hàng đợi dài ra, không tăng throughput (Little's Law: latency = concurrency / throughput).

Điểm vận hành hợp lý cho 1 process là khoảng c=10–40. Muốn hơn thì phải scale ngang (thêm instance), không phải tăng concurrency.

### 2.2 Tail latency

Lệnh: khởi động lại v2 với `MOCK_SLOW_RATE=<r>`, rồi `--requests 300 --concurrency 20 --out reports/load_v2_slow_<r>.json`

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 208.3 | 437.5 | 511.9 |
| 0.03 (mặc định) | 248.7 | 471.2 | 1714.3 |
| 0.1 | 357.2 | 1700.2 | 1750.2 |

**Nhận xét:** Từ 0 lên 0.03, **avg chỉ tăng ~19 %** (208 → 249 ms) nhưng **p99 tăng 3.3 lần** (512 → 1714 ms). Với 3 % request chậm, chúng nằm hết trong 1 % cuối, nên p99 nhảy ngay còn p95 gần như chưa đổi. Lên 0.1 (10 % chậm) thì cả p95 cũng rơi vào nhóm chậm (1700 ms), trong khi avg vẫn chỉ 357 ms, nhìn qua tưởng "ổn".

Average bị số đông request nhanh kéo xuống, nên che mất trải nghiệm của nhóm người dùng tệ nhất. Vì vậy SLO đặt theo p95/p99: "95 % người dùng chờ dưới 500 ms" là cam kết có ý nghĩa, còn "trung bình 250 ms" thì không.

(Ghi chú: ở `MOCK_SLOW_RATE=0`, error rate 2.33 % hơi vượt SLO 2 % do ngẫu nhiên của `MOCK_ERROR_RATE=0.01` trên mẫu 300 request: 7 lỗi so với kỳ vọng ~3. Mẫu nhỏ nên error rate dao động mạnh.)

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 58.1 | 108.8 | 113.7 |
| Tổng cost (USD) | 0.000418 | 0.000758 | 0.000790 |
| Cost / câu đúng (USD) | 0.00041775 | 0.00003607 | 0.00003436 |
| Quality gate | FAIL (ngưỡng 80 %) | PASS (ngưỡng 80 %) | PASS (ngưỡng 100 %, 0 regression) |

File: `reports/eval_v1.json`, `reports/eval_v2.json` (baseline v1), `reports/eval_v2_fixed.json` (baseline v2, `--min-accuracy 1.0`).

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA ... scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi.")` vào `KNOWLEDGE_BASE` |
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; ...")` |

Cả hai câu sai cùng một nguyên nhân: retrieval không tìm thấy tài liệu nào (KB không có keyword `hpa` hay `jwt`), nên LLM trả lời chung chung. Sửa ở `develop/utils/mock_llm.py` và chép sang `production/utils/mock_llm.py`. Chạy lại với `--baseline reports/eval_v2.json`: **2 câu được cải thiện, 0 regression**.

**Quality gate trong CI:** `run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có câu regression so với `--baseline`. Thử eval v1 với `--baseline reports/eval_v2.json`: accuracy 4.3 %, 20 câu regression, **exit=1**. Job [`.github/workflows/eval.yml`](.github/workflows/eval.yml) bật agent v2 rồi chạy `run_eval.py --min-accuracy 0.85`. Bước fail thì job fail, và khi bật branch protection "Require status checks to pass" thì PR không merge được.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- v2 tốn gần **gấp đôi token mỗi câu** (58 → 109): context từ retrieval làm prompt dài hơn. Tổng cost cũng gần gấp đôi.
- Đổi lại, accuracy tăng từ 4 % lên 91 %, nên **cost / câu đúng giảm ~11.6 lần** (0.000418 → 0.000036 USD). v1 rẻ nhưng gần như vô dụng; tiền trả cho câu sai là tiền mất trắng.
- Latency: v2 thêm bước retrieval (~20–85 ms trong trace) nhưng vẫn rất nhỏ so với thời gian gọi LLM.
- Bản sửa KB tăng token thêm ~4.5 % nhưng lên 100 %, nên cost / câu đúng còn giảm thêm. "Cost / câu đúng" là chỉ số đúng để so hai phiên bản; "cost / câu" sẽ khiến v1 trông tốt hơn.

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --scale agent=<n>` (agent, nginx, prometheus, grafana, jaeger, locust).

> **Sửa lỗi Dockerfile:** image agent ban đầu crash loop với `ModuleNotFoundError: No module named 'uvicorn'`. User `agent` được tạo với `-d /app`, nên `HOME=/app` và Python tìm user site ở `/app/.local`. Nhưng package được copy vào `/home/agent/.local`. Mình đã thêm `ENV PYTHONUSERBASE=/home/agent/.local` vào `production/Dockerfile`.
>
> **Lưu ý khi benchmark:** `docker compose run locust` (không có `--no-deps`) tự khởi động các service phụ thuộc và đưa `agent` về `replicas: 2` trong file compose. Kết quả là chạy "scale 1" ra 2 instance, còn "scale 3" bị cắt về 2. Mọi lần chạy Locust trong report đều dùng `run --no-deps`. Số instance đã kiểm tra trước và sau mỗi lần chạy bằng `docker ps` và `count(up{job="agent"})`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger, có event `exception`: [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 3 alert cùng **firing** (`AgentHighErrorRate`, `AgentHighLatencyP95`, `AgentInstanceDown`): [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

Unit test alert rules: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### Exercise 7.4 — trả lời câu hỏi

Số liệu lúc chụp dashboard (100 user Locust, 15:48:15Z, query Prometheus cùng thời điểm):

1. **p95 = 294.6 ms, avg = 234.2 ms, p99 = 1829 ms.** p95 và avg gần nhau, nghĩa là 95 % request khá đồng đều (~190–300 ms). Khoảng cách thật nằm ở **p99, gấp ~7.8 lần avg**: ~3 % request bị LLM xử lý chậm (`MOCK_SLOW_RATE=0.03`, ~1.7 s). Đó là tail latency mà avg che mất, đúng như trên panel "Latency /ask — p50/p95/p99": đường p99 tách hẳn lên ~1.8 s.
2. **Có, chia đều.** Panel "Requests/s theo instance" cho 2 instance là 30.95 và 30.58 req/s (lệch ~1 %). Nginx dùng round-robin. Gọi tay 6 request liên tiếp thì `X-Served-By` lần lượt là `.8 → .9 → .6 → .8 → .9 → .6` (lúc 3 instance).
3. **Input tokens/s (4730) ≈ 1.9 lần output tokens/s (2479)** vì input gồm câu hỏi, system prompt **và context retrieval** mà v2 nhét vào prompt, còn output chỉ là câu trả lời ngắn. Với RAG, input luôn lớn hơn output. Sang v1 (thí nghiệm E) không có context nên input/s giảm mạnh.
4. **`curl http://localhost:8080/metrics` → `HTTP/1.1 404 Not Found`.** `nginx.conf` chặn `/metrics` từ bên ngoài, vì metrics lộ thông tin nội bộ (route, tỉ lệ lỗi, cost, version). Prometheus scrape thẳng từng container `agent:8000` trong mạng nội bộ Docker (DNS service discovery), không đi qua Nginx.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền: Locust headless 30 user, 3 instance agent. Thời gian đo bằng script poll `/api/v1/alerts` mỗi 3 s, tính từ lúc `docker compose up -d` áp cấu hình mới.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (giá trị 19.3 %) | pending sau 25 s, **firing sau 86 s** | Error rate (Golden Signals) chuyển đỏ; "Requests/s theo status code" có đường 503 tăng; "LLM calls theo kết quả" có `error` tăng |
| B | `MOCK_SLOW_RATE=0.3` (giữ A) | `AgentHighLatencyP95` (p95 = 1.90 s) | pending sau 35 s, **firing sau 153 s** | Latency p95 (Golden Signals); panel p50/p95/p99: p95 nhảy lên ~1.9 s, p50 gần như không đổi |
| C | `LLM_MODEL=mock-llm-large` (A, B trả về mặc định) | `LLMCostBurnRateHigh` | pending sau 29 s, **firing sau 148 s** | "Cost burn rate (USD/giờ)": từ $1.57/giờ lên $33.6/giờ (~21 lần); p95 tăng lên 668 ms |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` | pending sau 13 s, **firing sau 42 s** | "Instances up" giảm từ 3 xuống 2; "Requests/s theo instance" mất một đường. Locust thấy 504 nhưng panel Error rate của agent không đổi (xem dưới) |
| E | `AGENT_VERSION=v1` | *Không có alert mới* | — | "Retrieval hit ratio" mất dữ liệu (v1 không retrieval); Tokens/s giảm; bảng "Phiên bản đang chạy" đổi sang `v1` (3 instance). Error rate vẫn 1.07 %. (`LLMCostBurnRateHigh` lúc đó còn firing chỉ vì cửa sổ `rate(...[5m])` vẫn chứa dữ liệu của thí nghiệm C.) |

Ảnh `prometheus-alert-firing.png` chụp lúc A + B + D cùng firing (16:02:59Z).

**Phân tích thời gian:** thời gian tới lúc firing ≈ thời gian để `rate(...[1m])` / `[5m]` tích đủ dữ liệu xấu + khoảng `for:` + chu kỳ scrape/evaluate (5–15 s).

- **A:** pending sau 25 s (cửa sổ 1 m mới có ~1/3 dữ liệu xấu nhưng 20 % lỗi đã vượt 5 %), cộng `for: 1m`, ra ~86 s.
- **B:** cần p95 > 1 s, nên phải có > 5 % request chậm trong cửa sổ 1 phút (pending ở 35 s), cộng `for: 2m`, ra ~153 s.
- **D:** chỉ cần 1 lần scrape thất bại (`up == 0`), cộng `for: 30s`, nên nhanh nhất (42 s).
- **C:** dùng cửa sổ 5 phút nhưng cost tăng ~21 lần nên chỉ cần ~30 s để vượt $2/giờ, cộng `for: 2m`, ra 148 s.

**Lỗi người dùng thấy nhưng agent không thấy.** Error report của Locust nền (30 user, suốt các thí nghiệm A–E) ghi 989 × 503, **1108 × 502** và **26 × 504**:

- 503 là lỗi do agent trả (thí nghiệm A), có trong metric `http_requests_total{status="503"}`.
- **504 (26 lần)** đến từ thí nghiệm D. Request đang nằm trên instance bị pause phải chờ hết `proxy_read_timeout 10s` (max latency Locust ghi được 10004 ms) rồi Nginx mới trả 504. Agent chưa xử lý xong nên metric của agent không đếm, và panel Error rate không phản ánh.
- **502 (1108 lần)** xảy ra mỗi lần `docker compose up -d` recreate agent để áp cấu hình. Nginx resolve DNS 10 s một lần, nên trong ~10 s nó vẫn gửi request tới IP của container cũ đã bị xoá. Agent không hề nhận các request này nên cũng không có trong metric.

Đúng như README phân tích: metric chỉ phản ánh những gì *chính service đó* thấy. Production cần giám sát cả tầng LB (status code của Nginx) và synthetic check từ bên ngoài. Deploy cũng cần rolling update có readiness check thay vì recreate đồng loạt.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Metric hạ tầng chỉ đo "có trả lời nhanh và không lỗi không", không đo "trả lời có đúng không". Cần đo chất lượng riêng:

1. **Quality gate trước deploy:** chạy eval golden dataset trong CI cho mọi thay đổi version/prompt/model ([`.github/workflows/eval.yml`](.github/workflows/eval.yml)). v1 đã bị chặn với exit=1 và 20 regression.
2. **Metric proxy cho chất lượng:** alert khi `agent_retrieval_total` hit ratio giảm đột ngột, khi tokens/request giảm bất thường, hoặc khi `agent_info{version}` đổi ngoài lịch release.
3. **Online eval:** định kỳ chạy golden dataset (synthetic probe) vào production, hoặc dùng LLM-as-judge chấm một mẫu traffic thật, rồi xuất `agent_eval_accuracy` thành gauge và alert khi giảm.
4. **Tín hiệu từ người dùng:** tỉ lệ 👍/👎, tỉ lệ hỏi lại, escalate sang người.

### 4.3 Debug bằng trace

Trace chậm nhất tìm được (100 user, 1 instance):

- `trace_id`: `2b24cc298c6f8cd9b6b2b8abc223869d`
- Tổng thời gian: **1781.0 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` (1684.1 ms, 94.6 %)**. `agent.retrieve_context` chỉ 85.0 ms (4.8 %). Nút thắt nằm ở LLM upstream, không phải code của agent.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 2b24cc298c6f8cd9b6b2b8abc223869d`):

```json
{"ts": "2026-11-25T15:50:45.626800+00:00", "level": "INFO", "service": "observable-agent", "instance": "fbe156d6dc94", "event": "llm_call", "trace_id": "2b24cc298c6f8cd9b6b2b8abc223869d", "span_id": "d4bd7718dafc05bc", "request_id": "2cc4958f5a7f", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 73, "output_tokens": 35, "cost_usd": 3.2e-05, "llm_ms": 1677.6}
{"ts": "2026-11-25T15:50:45.627353+00:00", "level": "INFO", "service": "observable-agent", "instance": "fbe156d6dc94", "event": "http_request", "trace_id": "2b24cc298c6f8cd9b6b2b8abc223869d", "span_id": "d4bd7718dafc05bc", "request_id": "2cc4958f5a7f", "method": "POST", "route": "/ask", "status": 200, "ms": 1780.6}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`):

- `trace_id`: `1225ec85b8c0c0e01c911f8ca0058bb3`, `POST /ask` 503, 107 ms.
- Span `chat mock-llm-small` (82.3 ms) có `error.type = upstream_unavailable` và event `exception`: `exception.type = utils.mock_llm.LLMError`, `exception.message = "Upstream LLM error: 503 Service Unavailable (mock)"`. Event này lan lên span `agent.run`.

```json
{"ts": "2026-11-25T15:50:56.020618+00:00", "level": "INFO", "service": "observable-agent", "instance": "fbe156d6dc94", "event": "llm_error", "trace_id": "1225ec85b8c0c0e01c911f8ca0058bb3", "span_id": "57c568158f782351", "request_id": "a9bc27453425", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T15:50:56.021463+00:00", "level": "INFO", "service": "observable-agent", "instance": "fbe156d6dc94", "event": "http_request", "trace_id": "1225ec85b8c0c0e01c911f8ca0058bb3", "span_id": "57c568158f782351", "request_id": "a9bc27453425", "method": "POST", "route": "/ask", "status": 503, "ms": 105.8}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh: `docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>`. Số liệu dòng `POST /ask` trong `scale_<n>_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.36 | 200 | 300 | 1700 | 86 / 7102 (1.21 %) |
| 3 | 59.35 | 190 | 230 | 1700 | 59 / 7099 (0.83 %) |

**Giải thích kết quả:**

- **RPS không đổi (59.4)** vì Locust là *closed-loop*: 100 user, mỗi user chờ `between(0.5, 2)` giây giữa hai request. Throughput tối đa ≈ 100 / (1.25 s chờ + ~0.24 s xử lý) ≈ 67 req/s. Tải do *người dùng* quyết định, không phải do server. 1 instance đã phục vụ đủ nên thêm instance không tăng RPS.
- **p95 cải thiện 300 → 230 ms (−23 %).** Mỗi container bị giới hạn `cpus: 0.5`. Với 1 instance, ~60 req/s đã làm CPU của nó bắt đầu bão hoà (in-flight tăng, có hàng đợi ngắn). 3 instance chia mỗi cái ~20 req/s nên hết xếp hàng.
- **p99 không đổi (1700 ms):** đây là 3 % request mà LLM xử lý chậm (~1.7 s). Panel "LLM latency p95" và trace cho thấy thời gian nằm trong span `chat mock-llm-*`. Scale agent không làm LLM nhanh hơn.

**Nút thắt nằm ở LLM upstream**, không ở agent. Muốn giảm tail latency phải xử lý ở tầng LLM: timeout + retry/hedged request, fallback sang model khác, cache câu trả lời, streaming để giảm time-to-first-token. Scale ngang chỉ có ích khi agent bị bão hoà CPU (như c=50/100 ở mục 2.1).

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average nói dối.** 3 % request chậm làm p99 tăng 3.3 lần mà avg chỉ tăng 19 %. SLO và alert phải đặt theo percentile, và phải đo bằng load test đủ mẫu, không phải 23 câu eval.
  2. **Hạ tầng xanh không có nghĩa là agent đúng.** Đổi sang v1 làm accuracy rơi từ 100 % xuống 4 % mà không alert nào kêu. Chất lượng cần quality gate riêng (golden dataset + exit code trong CI), và nên so "cost / câu đúng" thay vì "cost / câu".
  3. **Metrics → traces → logs nối với nhau bằng `trace_id`.** Dashboard báo p99 cao, Jaeger chỉ ra span `chat mock-llm-small` chiếm 94.6 %, grep log theo `trace_id` ra đúng request đó với `llm_ms=1677.6`. Ngoài ra phải hiểu công cụ đo: `docker compose run` đã lặng lẽ đổi số instance, Locust closed-loop khiến RPS không phản ánh năng lực server.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Alert theo error budget burn rate** (multi-window, ví dụ 1 h và 6 h) thay cho ngưỡng cố định, để vừa bắt sự cố nhanh vừa không ồn.
  - **Synthetic check từ bên ngoài** (blackbox exporter gọi `/ask` qua LB) và metric của Nginx/LB (504, upstream timeout), vì lỗi ở tầng LB không hiện trong metric của agent (thí nghiệm D).
  - **Chất lượng online:** gauge `agent_eval_accuracy` từ eval định kỳ hoặc LLM-as-judge trên mẫu traffic, alert khi giảm; alert khi retrieval hit ratio giảm.
  - **LLM:** time-to-first-token, tỉ lệ retry/fallback, token/request p95 (phát hiện prompt phình to), budget cost theo ngày (đã có trong agent Part 6) kèm alert dự báo hết budget.
  - **Saturation thật:** CPU throttling của container (`container_cpu_cfs_throttled_seconds_total`), độ dài hàng đợi, rồi autoscale theo in-flight requests thay vì chỉ CPU.
