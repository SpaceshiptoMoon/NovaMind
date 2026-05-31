#!/usr/bin/env python3
"""
一次性迁移：移除系统模型配置 (user_id=NULL 的记录)

运行方式：
    cd backend
    python scripts/migrate_remove_system_configs.py

功能：
    1. 统计 user_id IS NULL 的行数
    2. 删除所有系统配置记录
    3. 删除 idx_system_config 索引
    4. 将 user_id 列改为 NOT NULL

注意：
    - 运行前请确保已停止后端服务
    - 运行后启动新代码，SQLAlchemy create_all 会自动适配新表结构
    - 建议先备份数据库
"""
import asyncio
import sys
import os

# 将项目根目录添加到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def migrate():
    from sqlalchemy import text
    from src.core.database.database import async_engine

    print("=" * 60)
    print("迁移：移除系统模型配置 (user_id=NULL)")
    print("=" * 60)

    async with async_engine.begin() as conn:
        # Step 1: 统计系统配置行数
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM user_model_configs WHERE user_id IS NULL"
        ))
        count = result.scalar()
        print(f"\n[Step 1] 发现 {count} 条系统配置记录 (user_id=NULL)")

        if count > 0:
            # 展示将被删除的记录
            result = await conn.execute(text(
                "SELECT model_type, model, protocol FROM user_model_configs WHERE user_id IS NULL"
            ))
            rows = result.fetchall()
            print("  将删除的模型：")
            for row in rows:
                print(f"    - type={row[0]}, model={row[1]}, protocol={row[2]}")

            # Step 2: 删除系统配置
            await conn.execute(text(
                "DELETE FROM user_model_configs WHERE user_id IS NULL"
            ))
            print(f"\n[Step 2] 已删除 {count} 条系统配置记录")
        else:
            print("\n[Step 2] 无需删除，跳过")

        # Step 3: 删除系统配置索引
        try:
            await conn.execute(text(
                "DROP INDEX idx_system_config ON user_model_configs"
            ))
            print("\n[Step 3] 已删除 idx_system_config 索引")
        except Exception as e:
            print(f"\n[Step 3] 删除索引失败（可能不存在）: {e}")

        # Step 4: 将 user_id 改为 NOT NULL
        try:
            await conn.execute(text(
                "ALTER TABLE user_model_configs MODIFY COLUMN user_id BIGINT NOT NULL COMMENT '用户ID'"
            ))
            print("\n[Step 4] 已将 user_id 列改为 NOT NULL")
        except Exception as e:
            print(f"\n[Step 4] 修改列失败: {e}")

    print("\n" + "=" * 60)
    print("迁移完成！请启动新版本后端服务。")
    print("=" * 60)

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
