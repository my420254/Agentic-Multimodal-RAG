import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/yang/Agentic-Multimodal-RAG/backend")

from sqlmodel import Session, select
from app.core.database import engine, init_db
from app.models.models import CustomModel, ModelType

def seed():
    init_db()
    with Session(engine) as session:
        # Clear existing models
        existing = session.exec(select(CustomModel)).all()
        for m in existing:
            session.delete(m)
        session.commit()

        now = datetime.now(timezone.utc)
        models = [
            CustomModel(
                name="DeepSeek-Chat",
                model_type=ModelType.LLM,
                base_url="https://api.deepseek.com/v1",
                api_key="sk-0d387d9dab0546c096568b24221e398e",
                model_name="deepseek-chat",
                context_length=64000,
                is_active=True,
                created_at=now,
                updated_at=now,
            ),
            CustomModel(
                name="SiliconFlow BGE-M3",
                model_type=ModelType.EMBEDDING,
                base_url="https://api.siliconflow.cn/v1",
                api_key="sk-tofrzkduxftyzwqzbfjfklmoyrphvbbvuzceviphgorfoeei",
                model_name="BAAI/bge-m3",
                context_length=8192,
                is_active=True,
                created_at=now,
                updated_at=now,
            ),
            CustomModel(
                name="SiliconFlow Qwen3-VL",
                model_type=ModelType.VLM,
                base_url="https://api.siliconflow.cn/v1",
                api_key="sk-tofrzkduxftyzwqzbfjfklmoyrphvbbvuzceviphgorfoeei",
                model_name="Qwen/Qwen3-VL-8B-Instruct",
                context_length=32000,
                is_active=True,
                created_at=now,
                updated_at=now,
            ),
            CustomModel(
                name="SiliconFlow BGE-Reranker-v2-m3",
                model_type=ModelType.RERANK,
                base_url="https://api.siliconflow.cn/v1",
                api_key="sk-tofrzkduxftyzwqzbfjfklmoyrphvbbvuzceviphgorfoeei",
                model_name="BAAI/bge-reranker-v2-m3",
                context_length=8192,
                is_active=True,
                created_at=now,
                updated_at=now,
            ),
        ]
        session.add_all(models)
        session.commit()
        print(f"Successfully seeded {len(models)} models into local.db")

        for m in session.exec(select(CustomModel)).all():
            print(f" - [{m.model_type.value}] {m.name} -> {m.model_name} (ID: {m.id})")

if __name__ == "__main__":
    seed()
