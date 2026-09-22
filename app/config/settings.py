from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """项目配置，从 .env 文件读取"""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    model_name: str = "deepseek-v4-flash"
    temperature: float = 0.7

    # Eval Judge 与被测 Agent 使用不同模型，避免同模型自评。
    # 当前服务允许复用同一 API Key 和 Base URL。
    eval_judge_model: str = "deepseek-v4-pro"

    # ReAct 循环
    max_react_steps: int = 5

    # MCP 配置
    mcp_enabled: bool = False
    mcp_server_url: str = "http://127.0.0.1:9123/mcp"

    # RAG 配置（第5期）
    embedding_model: str = "text-embedding-v4"
    embedding_batch_size: int = 10
    # RAG 可使用独立的 DashScope OpenAI-compatible Embedding 服务。
    # 未配置时回退到聊天模型服务，保持普通 Demo 的向后兼容。
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""
    kb_dir: str = "app/agent/rag/knowledge"
    # 向量后端：numpy（手写余弦，教学透明，零依赖，默认）/ chroma（向量数据库，生产代表，需 pip install chromadb）
    rag_backend: str = "numpy"
    # NumpyBackend 的 JSON 索引路径
    kb_index_path: str = "app/sessions/kb_index.json"
    # ChromaBackend 的持久化目录与 collection 名
    chroma_persist_dir: str = "app/sessions/chroma"
    chroma_collection: str = "ecom_kb"

    # Multi-Agent 配置（第6期）
    multi_agent_enabled: bool = False

    # Memory 配置（第7期）
    memory_enabled: bool = True
    memory_dir: str = "app/sessions/memory"
    memory_user_id: str = "default"
    max_ltm_facts: int = 50

    # Skill 配置（第8期）
    skills_enabled: bool = True
    skills_dir: str = "app/agent/skills/definitions"

    # 电商业务状态：日常 Demo 与 Eval 共用同一个 SQLiteStore 实现
    ecom_db_path: str = "app/sessions/ecom_agent.db"
    ecom_user_id: str = "user-demo"

    # Evaluation 配置（第9期，离线评估工具，无聊天开关）
    # 以下两个字段仅用于容忍已有 .env；v4 运行代码不读取它们。
    eval_dataset_path: str | None = None
    eval_pass_threshold: float | None = None
    eval_canonical_dataset_path: str = "app/evaluation/dataset/canonical_cases.json"
    eval_use_judge: bool = True  # 是否启用 LLM-as-judge（质量/幻觉/过程合理性）
    eval_artifact_dir: str = "artifacts/eval"
    eval_gate_config: str = "eval_gate.toml"
    eval_rag_snapshot_path: str = "app/evaluation/rag_snapshot.json"

    # 多轮对话管理
    session_path: str = "app/sessions/session.json"
    history_threshold: int = 10  # 消息压缩策略通常为上下文达到一定的token数，例如claude code通常为达到最大上下文窗口的70%左右，此处简略为原始消息条数超过10轮
    history_keep_recent: int = 3  # 压缩时保留最近 3 条原始消息

    @property
    def embedding_api_key(self) -> str:
        return self.dashscope_api_key or self.openai_api_key

    @property
    def embedding_base_url(self) -> str:
        return self.dashscope_base_url or self.openai_base_url

    model_config = {
        "env_file": ".env",
        "protected_namespaces": ("settings_",),
    }


settings = Settings()
