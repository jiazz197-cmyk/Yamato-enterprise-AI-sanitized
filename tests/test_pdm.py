"""Debug script: 查询 quotation_tasks 表中的 keywords_payload"""
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from app.core.database import SessionLocal
from app.models.orm.quotation_task import QuotationTask


def main():
    db = SessionLocal()
    try:
        # 查询 id=214 的任务
        task = db.query(QuotationTask).filter(QuotationTask.id == 214).first()

        if not task:
            print("❌ Task id=214 not found")

            # 尝试查找最近的任务
            print("\n最近的 5 个任务:")
            recent = db.query(QuotationTask).order_by(QuotationTask.id.desc()).limit(5).all()
            for t in recent:
                print(f"  id={t.id}, task_id={t.task_id}, status={t.status}")
            return

        print("=" * 70)
        print(f"id:          {task.id}")
        print(f"task_id:     {task.task_id}")
        print(f"status:      {task.status}")
        print(f"progress:    {task.progress}")
        print(f"message:     {task.message}")
        print("=" * 70)

        if not task.result_payload:
            print("❌ result_payload is NULL")
            return

        print("\n📋 result_payload keys:")
        print(list(task.result_payload.keys()))

        # 提取 keywords_payload
        keywords_payload = task.result_payload.get("keywords_payload")

        if not keywords_payload:
            print("\n❌ keywords_payload not found in result_payload")
            return

        print("\n✅ keywords_payload:")
        print(json.dumps(keywords_payload, ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
