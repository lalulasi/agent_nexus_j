import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, func

# ==========================================
# 1. 宣告所有 ORM 模型的基底類別 (Base)
# ==========================================
class Base(DeclarativeBase):
    """
    SQLAlchemy 2.0 的新寫法。
    所有我們定義的資料表模型，都必須繼承這個 Base。
    它會在底層自動幫我們把 Python 類別映射到 PostgreSQL 的表結構。
    """
    pass


# ==========================================
# 2. 定義第一個業務模型：Agent 會話 (AgentSession)
# ==========================================
class AgentSession(Base):
    __tablename__ = "agent_sessions"

    # 使用 UUID 作為主鍵，避免流水號被猜測，也方便未來分散式擴容
    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True
    )

    # 會話標題（例如 LLM 自動生成的總結標題）
    title: Mapped[str] = mapped_column(String, nullable=False, default="New Conversation")

    # 紀錄當前使用的模型 (預留欄位)
    model_provider: Mapped[str] = mapped_column(String, nullable=True, default="deepseek")

    # 審計欄位 (Audit Fields)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<AgentSession(id={self.id}, title={self.title})>"