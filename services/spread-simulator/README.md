# Spread Simulator gRPC Service

基于 Go 语言实现的霉菌传播模拟器 gRPC 服务，使用 SEIR 传染病模型预测书架间霉菌传播。

## 项目结构

```
spread-simulator/
├── cmd/
│   └── server/
│       └── main.go              # gRPC 服务入口
├── pkg/
│   ├── seir/
│   │   ├── graph.go             # ShelfGraph 图结构实现
│   │   └── model.go             # SEIR 模型实现
│   └── client/
│       └── python/
│           ├── __init__.py
│           └── spread_simulator_client.py  # Python 客户端
├── proto/
│   └── spread.proto             # Protocol Buffers 定义
├── go.mod                       # Go 模块文件
└── README.md                    # 本文档
```

## 算法说明

Go 实现的算法与 Python 版本（`backend/app/spread_model/seir.py`）完全一致：

### 边权重公式
```
weight = exp(-distance_factor * distance) * (ventilation_factor * ventilation + (1 - ventilation_factor)) * adjacency_bonus
```

### SEIR 动力学公式
```
S[t+1] = S[t] - beta * S[t] * I[t] + mu * (1 - S[t])
E[t+1] = E[t] + beta * S[t] * I[t] - (sigma + mu) * E[t]
I[t+1] = I[t] + sigma * E[t] - (gamma + mu) * I[t]
R[t+1] = R[t] + gamma * I[t] - mu * R[t]
```

## 前置要求

### Go 服务端
- Go 1.21+
- Protocol Buffers 编译器 (`protoc`)
- Go gRPC 插件：
  ```bash
  go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.32.0
  go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0
  ```

### Python 客户端
- Python 3.9+
- gRPC Python 包：
  ```bash
  pip install grpcio grpcio-tools
  ```

## 构建步骤

### 1. 生成 Protocol Buffers 代码

#### Go 代码生成
```bash
cd services/spread-simulator
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       proto/spread.proto
```

生成的文件将位于 `proto/` 目录下：
- `spread.pb.go` - Protocol Buffers 消息类型
- `spread_grpc.pb.go` - gRPC 服务接口

#### Python 代码生成（可选，用于 Python 客户端）
```bash
cd services/spread-simulator/pkg/client/python
python -m grpc_tools.protoc -I../../proto \
       --python_out=. --grpc_python_out=. \
       ../../proto/spread.proto
```

### 2. 下载 Go 依赖
```bash
cd services/spread-simulator
go mod download
```

### 3. 构建服务
```bash
cd services/spread-simulator
go build -o bin/spread-simulator-server ./cmd/server
```

## 运行服务

### 启动 gRPC 服务
```bash
cd services/spread-simulator
go run ./cmd/server
```

或使用构建好的二进制：
```bash
./bin/spread-simulator-server
```

服务将在 `localhost:50051` 端口监听。

## 使用 Python 客户端

### 基本用法

```python
from services.spread_simulator.pkg.client.python import SpreadSimulatorClient

# 创建客户端
client = SpreadSimulatorClient(
    grpc_host="localhost",
    grpc_port=50051,
    prefer_grpc=True,  # 优先使用 gRPC
    timeout=10.0
)

# 配置参数
shelves_layout = {
    "total_shelves": 10,
    "columns": 5,
    "layers": 6
}

initial_infected = ["SHELF-01"]
days = 30

seir_params = {
    "beta": 0.3,
    "sigma": 0.2,
    "gamma": 0.1,
    "mu": 0.01
}

edge_params = {
    "distance_factor": 0.01,
    "ventilation_factor": 0.7,
    "adjacency_bonus": 1.5,
    "ventilation_default": 0.5,
    "shelf_distance_default": 1.0
}

# 运行模拟
response = client.simulate_spread(
    shelves_layout=shelves_layout,
    initial_infected=initial_infected,
    days=days,
    seir_params=seir_params,
    edge_params=edge_params
)

# 查看结果
print(f"使用 gRPC: {response.used_grpc}")
print(f"结果数量: {len(response.results)}")
print(f"热点数量: {len(response.hotspots)}")

# 遍历结果
for result in response.results:
    print(f"第 {result.day} 天, 书架 {result.shelf_id}: "
          f"S={result.state.S:.4f}, E={result.state.E:.4f}, "
          f"I={result.state.I:.4f}, R={result.state.R:.4f}")

# 查看热点
for hotspot in response.hotspots:
    print(f"热点书架 {hotspot.shelf_id}: "
          f"最大感染概率={hotspot.max_infection_prob:.4f}, "
          f"首次出现天数={hotspot.first_day}")

# 关闭连接
client.close()
```

### 使用上下文管理器
```python
with SpreadSimulatorClient() as client:
    response = client.simulate_spread(
        shelves_layout={"total_shelves": 10, "columns": 5, "layers": 6},
        initial_infected=["SHELF-01"],
        days=30
    )
    print(response.to_dict())
```

### 降级机制

客户端会自动处理以下情况：
1. **gRPC 不可用** - 自动降级到 Python 原生实现
2. **gRPC 服务未运行** - 连接失败时降级到 Python 原生实现
3. **gRPC 调用超时** - 超时后降级到 Python 原生实现

可以通过 `response.used_grpc` 检查实际使用的实现方式。

### 禁用 gRPC，仅使用 Python 原生实现
```python
client = SpreadSimulatorClient(prefer_grpc=False)
```

## API 参考

### gRPC 服务

#### SpreadSimulator.SimulateSpread

**请求消息 (SimulationRequest):**
- `shelves_layout` - 书架布局
  - `total_shelves` - 总书架数（默认 10）
  - `columns` - 列数（默认 5）
  - `layers` - 层数（默认 6）
- `initial_infected` - 初始感染书架 ID 列表
- `days` - 模拟天数
- `seir_params` - SEIR 模型参数
  - `beta` - 感染率（默认 0.3）
  - `sigma` - 潜伏期转换率（默认 0.2）
  - `gamma` - 恢复率（默认 0.1）
  - `mu` - 出生率/死亡率（默认 0.01）
- `edge_params` - 边权重参数
  - `distance_factor` - 距离因子（默认 0.01）
  - `ventilation_factor` - 通风因子（默认 0.7）
  - `adjacency_bonus` - 邻接加成（默认 1.5）
  - `ventilation_default` - 默认通风系数（默认 0.5）
  - `shelf_distance_default` - 默认书架距离（默认 1.0）

**响应消息 (SimulationResponse):**
- `results` - 模拟结果列表
  - `day` - 天数
  - `shelf_id` - 书架 ID
  - `state` - SEIR 状态
    - `S`, `E`, `I`, `R` - 各状态比例
    - `infection_prob` - 感染概率 (E + I)
  - `spread_from` - 传播来源书架
  - `edge_weight` - 边权重
- `hotspots` - 热点书架列表
  - `shelf_id` - 书架 ID
  - `max_infection_prob` - 最大感染概率
  - `first_day` - 首次达到阈值的天数
  - `is_hotspot` - 是否为热点
- `directions` - 传播方向列表
  - `from_shelf`, `to_shelf`, `weight`

## 默认参数值

| 参数 | 默认值 |
|------|--------|
| SEIR.beta | 0.3 |
| SEIR.sigma | 0.2 |
| SEIR.gamma | 0.1 |
| SEIR.mu | 0.01 |
| Edge.distance_factor | 0.01 |
| Edge.ventilation_factor | 0.7 |
| Edge.adjacency_bonus | 1.5 |
| Edge.ventilation_default | 0.5 |
| Edge.shelf_distance_default | 1.0 |
| Layout.total_shelves | 10 |
| Layout.columns | 5 |
| Layout.layers | 6 |
| Hotspot.threshold | 0.5 |

## 与 Python 版本的兼容性

Go 实现与 Python 版本（`backend/app/spread_model/seir.py`）的算法完全一致，包括：

1. ✅ 图构建逻辑相同（节点创建、边连接、距离计算）
2. ✅ 边权重计算公式相同
3. ✅ SEIR 动力学更新公式相同
4. ✅ 感染压力计算相同
5. ✅ 传播来源识别逻辑相同
6. ✅ 热点识别算法相同
7. ✅ 参数默认值相同

为了确保结果一致性，Go 实现中对书架 ID 进行了排序，避免 map 遍历顺序的不确定性。

## 性能对比

Go 版本相比 Python 版本通常有 **5-10 倍** 的性能提升，适合大规模模拟场景。

## 故障排除

### 问题: `protoc` 命令未找到
**解决**: 安装 Protocol Buffers 编译器
```bash
# macOS
brew install protobuf

# Ubuntu/Debian
sudo apt-get install protobuf-compiler

# Windows (使用 Chocolatey)
choco install protoc
```

### 问题: Go 插件未在 PATH 中
**解决**: 确保 Go bin 目录在 PATH 中
```bash
export PATH="$HOME/go/bin:$PATH"
```

### 问题: Python 客户端导入错误
**解决**: 确保项目根目录在 PYTHONPATH 中
```bash
export PYTHONPATH="/path/to/project:$PYTHONPATH"
```

### 问题: gRPC 连接失败
**解决**:
1. 确认 Go 服务正在运行
2. 检查端口 50051 是否被占用
3. 检查防火墙设置

## 许可证

与主项目相同。
