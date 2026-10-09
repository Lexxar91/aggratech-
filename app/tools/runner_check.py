import asyncio
import json

from app.assessment.runner import ExecutionRequest, RunnerClient
from app.core.config import Settings


async def run() -> None:
    """Проверяет реальное исполнение Python через настроенный mTLS-контроллер."""
    client = RunnerClient(Settings())
    try:
        result = await client.execute(
            ExecutionRequest(source="def solve(x): return x + 1", inputs=[41])
        )
        if result.status != "completed" or result.outputs != [42]:
            raise RuntimeError("runner_probe_failed")
        print(json.dumps(result.model_dump(), ensure_ascii=False))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(run())
